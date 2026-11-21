"""User-scoped race readiness: goal pace, prediction, intensity mix and long runs (SPEC-065).

Every pace is seconds per km and every average is time-weighted (`run_metrics`). Training
zones are offsets from the goal race pace, because a run only records its total distance
and time: a run's average pace is the only intensity signal there is.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.read_models.rounding import round_metric
from backend.read_models.run_statistics import PACE_RUN
from backend.run_metrics import pace_seconds_per_km

# Riegel's endurance model: T2 = T1 * (D2 / D1) ** 1.06.
RIEGEL_EXPONENT = 1.06
# A reference race at or above this temperature is slower than race-day weather usually is.
HOT_REFERENCE_C = 25
INTENSITY_WEEKS = 8
LONG_RUN_WEEKS = 8
LONG_RUN_CHART_WEEKS = 12
# A long run is at least 75% of the race distance; two of them in the last eight weeks
# is the usual minimum before a half marathon, and the last one comes two weeks out.
LONG_RUN_SHARE = 0.75
LONG_RUN_TARGET_COUNT = 2
LAST_LONG_RUN_DAYS_BEFORE = 14
# Zones as offsets (seconds per km) from goal race pace: easy is 45 s or more slower,
# steady 15–45 s slower, race pace from 10 s faster to 15 s slower, fast beyond that.
ZONES = (
    ("easy", "輕鬆", 45, None),
    ("steady", "穩定", 15, 45),
    ("race", "比賽配速", -10, 15),
    ("fast", "更快", None, -10),
)


def race_goal_values(db: Session, user_id: int) -> dict | None:
    goal = db.query(models.RaceGoal).filter(models.RaceGoal.user_id == user_id).one_or_none()
    if goal is None:
        return None
    return {
        "version": goal.version,
        "race_name": goal.race_name,
        "race_date": goal.race_date,
        "distance_km": goal.distance_km,
        "target_seconds": goal.target_seconds,
        "reference_distance_km": goal.reference_distance_km,
        "reference_seconds": goal.reference_seconds,
        "reference_temperature_c": goal.reference_temperature_c,
    }


def goal_pace(goal: dict) -> float:
    return goal["target_seconds"] / goal["distance_km"]


def zone_bounds(pace_goal: float) -> list[dict]:
    """Each zone's pace range; `min_pace` is the fast end, `max_pace` the slow end."""
    return [
        {"key": key, "label": label,
         "min_pace": None if low is None else round(pace_goal + low),
         "max_pace": None if high is None else round(pace_goal + high)}
        for key, label, low, high in ZONES
    ]


def zone_for(pace: float, pace_goal: float) -> str:
    offset = pace - pace_goal
    for key, _, low, high in ZONES:
        if (low is None or offset >= low) and (high is None or offset < high):
            return key
    return "fast"


def predict_seconds(reference_seconds: float, reference_km: float, distance_km: float) -> int:
    return round(reference_seconds * (distance_km / reference_km) ** RIEGEL_EXPONENT)


def _prediction(goal: dict) -> dict | None:
    if goal["reference_seconds"] is None or goal["reference_distance_km"] is None:
        return None
    predicted = predict_seconds(goal["reference_seconds"], goal["reference_distance_km"], goal["distance_km"])
    temperature = goal["reference_temperature_c"]
    return {
        "reference_distance_km": goal["reference_distance_km"],
        "reference_seconds": goal["reference_seconds"],
        "reference_pace": pace_seconds_per_km(goal["reference_seconds"], goal["reference_distance_km"]),
        "reference_temperature_c": temperature,
        "hot_reference": temperature is not None and temperature >= HOT_REFERENCE_C,
        "predicted_seconds": predicted,
        "predicted_pace": pace_seconds_per_km(predicted, goal["distance_km"]),
        "margin_seconds": goal["target_seconds"] - predicted,
    }


def _intensity(runs: list[tuple[date, float, int | None]], pace_goal: float) -> dict:
    counts = {key: 0 for key, _, _, _ in ZONES}
    distance = {key: 0.0 for key, _, _, _ in ZONES}
    time = {key: 0 for key, _, _, _ in ZONES}
    untimed = 0
    for _, km, seconds in runs:
        if seconds is None:
            untimed += 1
            continue
        key = zone_for(seconds / km, pace_goal)
        counts[key] += 1
        distance[key] += km
        time[key] += seconds
    total = sum(time.values())
    return {
        "weeks": INTENSITY_WEEKS,
        "total_seconds": total,
        "untimed_runs": untimed,
        "zones": [{"key": key, "label": label, "runs": counts[key], "km": round_metric(distance[key]),
                   "seconds": time[key], "share": round_metric(time[key] / total * 100, 1) if total else 0.0}
                  for key, label, _, _ in ZONES],
    }


def _long_runs(runs: list[tuple[date, float, int | None]], goal: dict, as_of: date) -> dict:
    distance = goal["distance_km"]
    threshold = round_metric(distance * LONG_RUN_SHARE, 1)
    start = as_of - timedelta(weeks=LONG_RUN_WEEKS)
    recent = [run for run in runs if run[0] > start]
    qualifying = [run for run in recent if run[1] >= threshold]
    longest_recent = max(recent, key=lambda run: (run[1], run[0]), default=None)
    longest_ever = max(runs, key=lambda run: (run[1], run[0]), default=None)
    monday = as_of - timedelta(days=as_of.weekday())
    weekly = []
    for offset in range(LONG_RUN_CHART_WEEKS - 1, -1, -1):
        week = monday - timedelta(weeks=offset)
        rows = [run for run in runs if week <= run[0] < week + timedelta(days=7)]
        weekly.append({"week_start": week.isoformat(), "km": round_metric(sum(run[1] for run in rows)),
                       "longest_km": round_metric(max((run[1] for run in rows), default=0.0)),
                       "partial": week + timedelta(days=6) > as_of})

    def run_row(run: tuple[date, float, int | None] | None) -> dict | None:
        if run is None:
            return None
        return {"date": run[0].isoformat(), "km": round_metric(run[1]),
                "pace": pace_seconds_per_km(run[2], run[1])}

    return {
        "weeks": LONG_RUN_WEEKS,
        "threshold_km": threshold,
        "target_count": LONG_RUN_TARGET_COUNT,
        "count": len(qualifying),
        "runs": [run_row(run) for run in qualifying],
        "longest_recent": run_row(longest_recent),
        "longest_ever": run_row(longest_ever),
        "longest_recent_percent": round(longest_recent[1] / distance * 100) if longest_recent else 0,
        "enough": len(qualifying) >= LONG_RUN_TARGET_COUNT,
        "last_long_run_by": (date.fromisoformat(goal["race_date"])
                             - timedelta(days=LAST_LONG_RUN_DAYS_BEFORE)).isoformat(),
        "weekly": weekly,
        "average_weekly_km": round_metric(sum(run[1] for run in recent) / LONG_RUN_WEEKS),
    }


def race_readiness(db: Session, user_id: int, as_of: date) -> dict:
    goal = race_goal_values(db, user_id)
    if goal is None:
        return {"as_of": as_of.isoformat(), "goal": None}
    pace_goal = goal_pace(goal)
    rows = (
        db.query(models.Run.date, models.Run.km, models.Run.duration_seconds)
        # Road runs only: trail climbs and hikes would distort pace (SPEC-096).
        .filter(models.Run.user_id == user_id, PACE_RUN, models.Run.date <= as_of.isoformat())
        .all()
    )
    runs = sorted((date.fromisoformat(day), float(km), seconds) for day, km, seconds in rows)
    intensity_start = as_of - timedelta(weeks=INTENSITY_WEEKS)
    return {
        "as_of": as_of.isoformat(),
        "goal": goal,
        "days_left": (date.fromisoformat(goal["race_date"]) - as_of).days,
        "goal_pace": round(pace_goal),
        "zones": zone_bounds(pace_goal),
        "prediction": _prediction(goal),
        "intensity": _intensity([run for run in runs if run[0] > intensity_start], pace_goal),
        "long_runs": _long_runs(runs, goal, as_of),
    }
