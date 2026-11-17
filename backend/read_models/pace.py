"""User-scoped pace analytics: trend, monthly volume, training load, distance and spread (SPEC-064).

Pace is always time-weighted (total seconds / total timed km, `run_metrics`). Volume
counts every run, timed or not, because training load does not depend on a watch.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.read_models.rounding import round_metric
from backend.run_metrics import pace_seconds_per_km

ROLLING_DAYS = 30
LOAD_WEEKS = 4
LOAD_BUCKET_KM = 10
LAG_MONTHS = 3
LOAD_MIN_BUCKET_WEEKS = 3
MIN_CORRELATION_POINTS = 8
DISTRIBUTION_BIN_SECONDS = 15
DISTANCE_BANDS: tuple[tuple[float, float | None], ...] = (
    (0, 5), (5, 8), (8, 12), (12, 16), (16, 22), (22, None),
)

Run = tuple[date, float, int | None]


def _pace(runs: list[Run]) -> int | None:
    timed = [(km, seconds) for _, km, seconds in runs if seconds is not None]
    if not timed:
        return None
    return pace_seconds_per_km(sum(seconds for _, seconds in timed), sum(km for km, _ in timed))


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _rolling(timed: list[Run]) -> list[dict]:
    """Time-weighted pace of the 30 days ending on each running day."""
    points: list[dict] = []
    days = sorted({day for day, _, _ in timed})
    start = 0
    for day in days:
        while timed[start][0] <= day - timedelta(days=ROLLING_DAYS):
            start += 1
        window = [run for run in timed[start:] if run[0] <= day]
        points.append({"date": day.isoformat(), "pace": _pace(window)})
    return points


def _monthly(runs: list[Run]) -> list[dict]:
    months: dict[str, list[Run]] = {}
    for run in runs:
        months.setdefault(run[0].strftime("%Y-%m"), []).append(run)
    first, last = min(months), max(months)
    rows: list[dict] = []
    year, month = int(first[:4]), int(first[5:])
    while f"{year:04d}-{month:02d}" <= last:
        key = f"{year:04d}-{month:02d}"
        rows_in = months.get(key, [])
        rows.append({
            "month": key,
            "km": round_metric(sum(km for _, km, _ in rows_in)),
            "timed_km": round_metric(sum(km for _, km, seconds in rows_in if seconds is not None)),
            "runs": len(rows_in),
            "pace": _pace(rows_in),
        })
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return rows


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < MIN_CORRELATION_POINTS or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return round(statistics.correlation(xs, ys), 2)


def _load(runs: list[Run], as_of: date) -> dict:
    """Each week's pace against the average weekly volume of the four weeks before it."""
    weekly_km: dict[date, float] = {}
    weekly_runs: dict[date, list[Run]] = {}
    for run in runs:
        week = _week_start(run[0])
        weekly_km[week] = weekly_km.get(week, 0.0) + run[1]
        weekly_runs.setdefault(week, []).append(run)
    first = min(weekly_km)
    points: list[dict] = []
    week = first + timedelta(weeks=LOAD_WEEKS)
    while week <= _week_start(as_of):
        pace = _pace(weekly_runs.get(week, []))
        if pace is not None:
            prior = sum(weekly_km.get(week - timedelta(weeks=offset), 0.0)
                        for offset in range(1, LOAD_WEEKS + 1)) / LOAD_WEEKS
            points.append({"week_start": week.isoformat(), "prior_week_km": round_metric(prior),
                           "km": round_metric(weekly_km.get(week, 0.0)), "pace": pace})
        week += timedelta(weeks=1)
    xs = [float(point["prior_week_km"]) for point in points]
    ys = [float(point["pace"]) for point in points]
    trend = None
    if _correlation(xs, ys) is not None:
        slope, intercept = statistics.linear_regression(xs, ys)
        trend = {"slope_seconds_per_10km": round(slope * 10, 1), "intercept": round(intercept, 1),
                 "min_km": min(xs), "max_km": max(xs)}
    groups: dict[int, list[float]] = {}
    for x, y in zip(xs, ys, strict=True):
        groups.setdefault(int(x // LOAD_BUCKET_KM) * LOAD_BUCKET_KM, []).append(y)
    buckets = [
        {"min_km": low, "max_km": low + LOAD_BUCKET_KM, "weeks": len(values),
         "median_pace": round(statistics.median(values))}
        for low, values in sorted(groups.items()) if len(values) >= LOAD_MIN_BUCKET_WEEKS
    ]
    comparison = None
    if len(buckets) >= 2:
        fastest = min(buckets, key=lambda bucket: (bucket["median_pace"], bucket["min_km"]))
        if fastest is not buckets[0]:
            comparison = {"low": buckets[0], "fast": fastest,
                          "seconds_faster": buckets[0]["median_pace"] - fastest["median_pace"]}
    return {"weeks": LOAD_WEEKS, "points": points, "correlation": _correlation(xs, ys),
            "trend": trend, "buckets": buckets, "comparison": comparison}


def _monthly_lag(monthly: list[dict]) -> dict:
    """How the average volume of the three months before a month relates to its pace."""
    xs: list[float] = []
    ys: list[float] = []
    for index in range(LAG_MONTHS, len(monthly)):
        if monthly[index]["pace"] is not None:
            xs.append(sum(float(row["km"]) for row in monthly[index - LAG_MONTHS:index]) / LAG_MONTHS)
            ys.append(float(monthly[index]["pace"]))
    return {"months": LAG_MONTHS, "same_month_correlation": _correlation(
        [float(row["km"]) for row in monthly if row["pace"] is not None],
        [float(row["pace"]) for row in monthly if row["pace"] is not None],
    ), "prior_months_correlation": _correlation(xs, ys), "points": len(xs)}


def _distance(timed: list[Run]) -> list[dict]:
    bands: list[dict] = []
    for low, high in DISTANCE_BANDS:
        rows = [run for run in timed if run[1] >= low and (high is None or run[1] < high)]
        valid = [pace for pace in (pace_seconds_per_km(run[2], run[1]) for run in rows) if pace is not None]
        bands.append({
            "min_km": low, "max_km": high, "runs": len(rows),
            "km": round_metric(sum(km for _, km, _ in rows)),
            "pace": _pace(rows), "fastest_pace": min(valid) if valid else None,
        })
    return bands


def _distribution(timed: list[Run]) -> dict:
    """Runs per 15-second pace bin; the outer 5% on each side share the end bins."""
    paces = sorted(p for p in (pace_seconds_per_km(run[2], run[1]) for run in timed if run[2] is not None)
                   if p is not None)
    if not paces:
        return {"bin_seconds": DISTRIBUTION_BIN_SECONDS, "bins": [], "median_pace": None}
    tail = len(paces) // 20
    low = paces[tail] // DISTRIBUTION_BIN_SECONDS * DISTRIBUTION_BIN_SECONDS
    high = math.ceil((paces[-1 - tail] + 1) / DISTRIBUTION_BIN_SECONDS) * DISTRIBUTION_BIN_SECONDS
    edges = list(range(low, high + 1, DISTRIBUTION_BIN_SECONDS))
    bins = [{"min_pace": edges[index], "max_pace": edges[index + 1], "runs": 0,
             "open_min": index == 0, "open_max": index == len(edges) - 2}
            for index in range(len(edges) - 1)]
    for pace in paces:
        index = min(max((pace - low) // DISTRIBUTION_BIN_SECONDS, 0), len(bins) - 1)
        bins[index]["runs"] += 1
    return {"bin_seconds": DISTRIBUTION_BIN_SECONDS, "bins": bins, "median_pace": round(statistics.median(paces))}


def _summary(timed: list[Run], as_of: date) -> dict:
    first_end = timed[0][0] + timedelta(days=90)
    first = [run for run in timed if run[0] < first_end]
    recent = [run for run in timed if run[0] > as_of - timedelta(days=90)]
    recent_30 = [run for run in timed if run[0] > as_of - timedelta(days=ROLLING_DAYS)]
    return {
        "first_date": timed[0][0].isoformat(),
        "first_90_days_pace": _pace(first),
        "recent_90_days_pace": _pace(recent),
        "recent_30_days_pace": _pace(recent_30),
    }


def pace_analysis(db: Session, user_id: int, as_of: date) -> dict:
    rows = (
        db.query(models.Run.date, models.Run.km, models.Run.duration_seconds)
        .filter(models.Run.user_id == user_id, models.Run.date <= as_of.isoformat())
        .order_by(models.Run.date, models.Run.id)
        .all()
    )
    runs: list[Run] = [(date.fromisoformat(day), float(km), seconds) for day, km, seconds in rows]
    timed = [run for run in runs if run[2] is not None]
    base = {"as_of": as_of.isoformat(), "timed_run_count": len(timed),
            "untimed_run_count": len(runs) - len(timed)}
    if not timed:
        return {**base, "summary": None, "runs": [], "rolling": [], "monthly": [],
                "load": {"weeks": LOAD_WEEKS, "points": [], "correlation": None, "trend": None, "buckets": [],
                         "comparison": None},
                "monthly_lag": {"months": LAG_MONTHS, "same_month_correlation": None,
                                "prior_months_correlation": None, "points": 0},
                "distance": [], "distribution": {"bin_seconds": DISTRIBUTION_BIN_SECONDS, "bins": [],
                                                 "median_pace": None}}
    monthly = _monthly(runs)
    return {
        **base,
        "summary": _summary(timed, as_of),
        "runs": [{"date": day.isoformat(), "km": round_metric(km), "pace": pace_seconds_per_km(seconds, km)}
                 for day, km, seconds in timed if seconds is not None],
        "rolling": _rolling(timed),
        "monthly": monthly,
        "monthly_lag": _monthly_lag(monthly),
        "load": _load(runs, as_of),
        "distance": _distance(timed),
        "distribution": _distribution(timed),
    }
