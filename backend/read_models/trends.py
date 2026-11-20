"""User-scoped training trends: daily heatmap, streaks, weekly load, goal pace and shoe rotation."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend import models
from backend.read_models import goal_progress
from backend.read_models.rounding import round_metric
from backend.run_metrics import pace_seconds_per_km

WEEKS = 16
ROLLING_WEEKS = 4
# Load guard: flag a week more than 30% above the average of the previous four weeks
# (acute:chronic ratio > 1.3). Week-over-week 10% flags normal recreational variation.
SPIKE_PERCENT = 30.0
SPIKE_MIN_BASE_KM = 5.0
IDLE_DAYS = 30


def trends_end(year: int, as_of: date) -> date | None:
    """Last day with readable data for the year; None for a future year."""
    if year > as_of.year:
        return None
    return as_of if year == as_of.year else date(year, 12, 31)


DailyRuns = tuple[float, float, int, float, float]
NO_RUNS: DailyRuns = (0.0, 0.0, 0, 0.0, 0.0)


def _daily_km(db: Session, user_id: int, start: date, end: date) -> dict[date, DailyRuns]:
    """Per day: (total distance, longest single run, number of runs, timed seconds, timed distance)."""
    timed = models.Run.duration_seconds.isnot(None)
    rows = (
        db.query(models.Run.date, func.sum(models.Run.km), func.max(models.Run.km), func.count(models.Run.id),
                 func.sum(case((timed, models.Run.duration_seconds), else_=0)),
                 func.sum(case((timed, models.Run.km), else_=0)))
        .filter(
            models.Run.user_id == user_id,
            models.Run.date >= start.isoformat(),
            models.Run.date <= end.isoformat(),
        )
        .group_by(models.Run.date)
        .all()
    )
    return {
        date.fromisoformat(day): (float(km or 0), float(longest or 0), int(count or 0),
                                  float(seconds or 0), float(timed_km or 0))
        for day, km, longest, count, seconds, timed_km in rows
    }


def run_streaks(days: list[date], end: date) -> dict:
    longest, longest_end, run, previous = 0, None, 0, None
    for day in days:
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        if run > longest:
            longest, longest_end = run, day
        previous = day
    # The current streak survives until a full day passes without a run.
    current = run if previous is not None and (end - previous).days <= 1 else 0
    return {
        "longest_days": longest,
        "longest_end": longest_end.isoformat() if longest_end else None,
        "current_days": current,
    }


def weekly_window(year: int, end: date, weeks_end: date | None) -> tuple[date, dict]:
    """The 16-week window ending at ``weeks_end`` inside the selected year (SPEC-072).

    The latest window is the default; earlier windows stop at the week holding 1 January.
    """
    first_monday = date(year, 1, 1) - timedelta(days=date(year, 1, 1).weekday())
    earliest_end = first_monday + timedelta(weeks=WEEKS - 1, days=6)
    window_end = end if weeks_end is None else min(end, max(weeks_end, min(earliest_end, end)))
    window_first = window_end - timedelta(days=window_end.weekday()) - timedelta(weeks=WEEKS - 1)
    return window_end, {
        "end": window_end.isoformat(),
        "has_earlier": window_first > first_monday,
        "has_later": window_end < end,
    }


def _weekly(daily: dict[date, DailyRuns], end: date, weekly_goal: float | None,
            window_end: date | None = None) -> list[dict]:
    """Weeks ending at ``window_end``; a week is partial when the data ``end`` cuts it short."""
    last_day = end if window_end is None else window_end
    last_monday = last_day - timedelta(days=last_day.weekday())
    first_monday = last_monday - timedelta(weeks=WEEKS + ROLLING_WEEKS - 1)
    totals = []
    for index in range(WEEKS + ROLLING_WEEKS):
        monday = first_monday + timedelta(weeks=index)
        days = [daily.get(monday + timedelta(days=d), NO_RUNS) for d in range(7)]
        totals.append((monday, sum(day[0] for day in days), max(day[1] for day in days)))
    weeks = []
    for index in range(ROLLING_WEEKS, len(totals)):
        monday, km, longest = totals[index]
        baseline = sum(value for _, value, _ in totals[index - ROLLING_WEEKS:index]) / ROLLING_WEEKS
        rolling = sum(value for _, value, _ in totals[index - ROLLING_WEEKS + 1:index + 1]) / ROLLING_WEEKS
        change = (km - baseline) / baseline * 100 if baseline > 0 else None
        weeks.append({
            "week_start": monday.isoformat(),
            "km": round_metric(km),
            "average_km": round_metric(rolling),
            "baseline_km": round_metric(baseline),
            "change_percent": round_metric(change, 1) if change is not None else None,
            "spike": bool(baseline >= SPIKE_MIN_BASE_KM and change is not None and change > SPIKE_PERCENT),
            "partial": monday + timedelta(days=6) > end,
            "longest_km": round_metric(longest),
            "goal_met": weekly_goal is not None and km + 0.005 >= weekly_goal,
        })
    return weeks


def _weekday_mix(daily: dict[date, DailyRuns], start: date, end: date) -> list[dict]:
    """Monday-first distance, running days, runs and time-weighted pace per weekday (SPEC-064)."""
    rows = [{"weekday": weekday, "km": 0.0, "run_days": 0, "runs": 0} for weekday in range(7)]
    timed = [[0.0, 0.0] for _ in range(7)]
    for day, (km, _, runs, seconds, timed_km) in daily.items():
        if start <= day <= end and km > 0:
            row = rows[day.weekday()]
            row["km"] = float(row["km"]) + km
            row["run_days"] = int(row["run_days"]) + 1
            row["runs"] = int(row["runs"]) + runs
            timed[day.weekday()][0] += seconds
            timed[day.weekday()][1] += timed_km
    return [{**row, "km": round_metric(float(row["km"])),
             "pace": pace_seconds_per_km(timed[index][0], timed[index][1])}
            for index, row in enumerate(rows)]


def training_trends(db: Session, user_id: int, year: int, as_of: date,
                    weeks_end: date | None = None) -> dict:
    end = trends_end(year, as_of)
    goal = goal_progress.goal_values(db, user_id)
    days_in_year = goal_progress.days_in_year(year)
    yearly_goal = goal["yearly_km"]
    goal_line = [goal_progress.yearly_goal_to_date(yearly_goal, year, day + 1) for day in range(days_in_year)]
    goal_active = year >= goal["start_year"]
    # The weekly target has the annual goal line's slope: yearly goal x 7 / days in the year.
    weekly_goal_km = goal_progress.yearly_goal_to_date(yearly_goal, year, 7)
    base = {
        "year": year,
        "end_date": end.isoformat() if end else None,
        "thresholds": {"spike_percent": SPIKE_PERCENT, "spike_min_base_km": SPIKE_MIN_BASE_KM},
        "weekly_goal": {"active": goal_active, "km": weekly_goal_km},
    }
    if end is None:
        return {
            **base, "daily": [], "streaks": run_streaks([], as_of), "weekly": [],
            "weekly_window": {"end": None, "has_earlier": False, "has_later": False},
            "weekday": _weekday_mix({}, as_of, as_of),
            "cumulative": {
                "goal_active": goal_active, "yearly_goal_km": yearly_goal,
                "actual_km": [], "goal_km": goal_line, "ytd_km": 0.0, "expected_km": 0.0,
                "delta_km": 0.0, "projected_km": 0.0,
            },
        }

    year_start = date(year, 1, 1)
    window_end, window = weekly_window(year, end, weeks_end)
    weekly_start = window_end - timedelta(days=window_end.weekday()) - timedelta(weeks=WEEKS + ROLLING_WEEKS - 1)
    daily = _daily_km(db, user_id, min(year_start, weekly_start), end)
    year_days = sorted(day for day, (km, *_) in daily.items() if day >= year_start and km > 0)

    elapsed = (end - year_start).days + 1
    actual, running = [], 0.0
    for offset in range(elapsed):
        running += daily.get(year_start + timedelta(days=offset), NO_RUNS)[0]
        actual.append(round_metric(running))
    ytd = actual[-1] if actual else 0.0
    expected = goal_line[elapsed - 1]
    return {
        **base,
        "daily": [{"date": day.isoformat(), "km": round_metric(daily[day][0])} for day in year_days],
        "streaks": run_streaks(year_days, end),
        "weekly": _weekly(daily, end, weekly_goal_km if goal_active else None, window_end),
        "weekly_window": window,
        "weekday": _weekday_mix(daily, year_start, end),
        "cumulative": {
            "goal_active": goal_active,
            "yearly_goal_km": yearly_goal,
            "actual_km": actual,
            "goal_km": goal_line,
            "ytd_km": ytd,
            "expected_km": expected,
            "delta_km": round_metric(ytd - expected),
            "projected_km": round_metric(ytd / elapsed * days_in_year),
        },
    }


def shoe_timeline(db: Session, user_id: int, as_of: date) -> dict:
    """First/last logged run per owned active shoe, oldest rotation first.

    Retired and deleted shoes are no longer in rotation, so they are omitted.
    ``shoe_km`` is the shoe's total mileage; ``other_km`` is the part outside the
    run log (warm-ups and walks recorded on the shoe, SPEC-067).
    """
    rows = (
        db.query(
            models.Shoe,
            func.min(models.Run.date), func.max(models.Run.date),
            func.sum(models.Run.km), func.count(models.Run.id),
        )
        .join(models.Run, (models.Run.shoe_id == models.Shoe.id) & (models.Run.user_id == user_id))
        .filter(
            models.Shoe.user_id == user_id,
            models.Shoe.is_deleted.is_(False),
            models.Shoe.is_retired.is_(False),
        )
        .group_by(models.Shoe.id)
        .order_by(func.min(models.Run.date), models.Shoe.id)
        .all()
    )
    shoes = []
    for shoe, first, last, km, count in rows:
        idle = (as_of - date.fromisoformat(last)).days
        shoes.append({
            "shoe_id": shoe.id,
            "first_run_date": first,
            "last_run_date": last,
            "km": round_metric(km),
            "shoe_km": round_metric(shoe.mileage),
            "other_km": round_metric(shoe.mileage - (km or 0)),
            "run_count": int(count),
            "days_since_last_run": max(0, idle),
            "idle": idle > IDLE_DAYS,
        })
    return {"as_of": as_of.isoformat(), "idle_days": IDLE_DAYS, "shoes": shoes}
