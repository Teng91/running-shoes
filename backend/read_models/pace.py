"""User-scoped pace trend for the race-preparation charts (SPEC-064, SPEC-065).

Pace is always time-weighted (total seconds / total timed km, `run_metrics`). With a race
goal, each run also carries its intensity zone relative to the goal race pace.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.read_models.race_readiness import goal_pace, race_goal_values, zone_bounds, zone_for
from backend.read_models.rounding import round_metric
from backend.run_metrics import pace_seconds_per_km

ROLLING_DAYS = 30

Run = tuple[date, float, int | None]


def _pace(runs: list[Run]) -> int | None:
    timed = [(km, seconds) for _, km, seconds in runs if seconds is not None]
    if not timed:
        return None
    return pace_seconds_per_km(sum(seconds for _, seconds in timed), sum(km for km, _ in timed))


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


def _summary(timed: list[Run], as_of: date) -> dict:
    first_end = timed[0][0] + timedelta(days=90)
    return {
        "first_date": timed[0][0].isoformat(),
        "first_90_days_pace": _pace([run for run in timed if run[0] < first_end]),
        "recent_90_days_pace": _pace([run for run in timed if run[0] > as_of - timedelta(days=90)]),
        "recent_30_days_pace": _pace([run for run in timed if run[0] > as_of - timedelta(days=ROLLING_DAYS)]),
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
    goal = race_goal_values(db, user_id)
    pace_goal = goal_pace(goal) if goal else None
    base = {"as_of": as_of.isoformat(), "timed_run_count": len(timed),
            "untimed_run_count": len(runs) - len(timed),
            "goal_pace": round(pace_goal) if pace_goal else None,
            "zones": zone_bounds(pace_goal) if pace_goal else []}
    if not timed:
        return {**base, "summary": None, "runs": [], "rolling": []}
    points = []
    for day, km, seconds in timed:
        pace = pace_seconds_per_km(seconds, km)
        points.append({"date": day.isoformat(), "km": round_metric(km), "pace": pace,
                       "zone": zone_for(seconds / km, pace_goal) if pace_goal and seconds else None})
    return {**base, "summary": _summary(timed, as_of), "runs": points, "rolling": _rolling(timed)}
