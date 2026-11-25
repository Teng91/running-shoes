"""User-scoped weekly race training plan (SPEC-119).

The plan is a deterministic function of the race goal and the runner's own volume, so the
same data always gives the same plan and past weeks never move:

- The plan starts the runner's chosen number of weeks before race week (4–24, including race
  week); a goal without a choice uses its distance's default.
- Its baseline is the average weekly distance of the four weeks before the plan starts (or
  before this week, while the plan has not started), so it no longer changes once it starts.
- Build weeks grow at most 10% a week, every fourth week is a lighter recovery week, then the
  plan tapers into race week. The long run grows the same way, is at most half the week, and
  the last full long run ends at least two weeks before the race (as race readiness asks).

Volume counts every training activity (`TRAINING_RUN`); the AI coach only explains the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.read_models.race_readiness import LONG_RUN_SHARE, race_readiness
from backend.read_models.rounding import round_metric
from backend.read_models.run_statistics import TRAINING_RUN

BASELINE_WEEKS = 4
# A beginner still gets a plan: the baseline is never below this weekly distance.
MIN_BASE_KM = 15
MIN_LONG_KM = 5
WEEKLY_GROWTH = 1.10
# Peak volume is at most 50% above the baseline, however long the plan is.
MAX_PEAK_GROWTH = 1.5
RECOVERY_EVERY = 4
RECOVERY_SHARE = 0.8
LONG_RUN_MAX_SHARE = 0.5
RACE_PACE_SHARE = 0.15
RACE_WEEK_EASY_SHARE = 0.3
# A week counts as done at 90% of its distance and long run, as partly done at 60%.
DONE_SHARE = 0.9
PARTIAL_SHARE = 0.6


MIN_PLAN_WEEKS = 4
MAX_PLAN_WEEKS = 24


@dataclass(frozen=True)
class Profile:
    weeks: int
    peak_km: int
    long_peak_km: int
    taper: tuple[float, ...]  # share of peak volume in each week between the build and race week


# Upper distance (km) for each profile: 5K, 10K, half and full marathon.
PROFILES = (
    (5.5, Profile(weeks=8, peak_km=30, long_peak_km=10, taper=(0.7,))),
    (10.5, Profile(weeks=10, peak_km=40, long_peak_km=14, taper=(0.7,))),
    (21.5, Profile(weeks=12, peak_km=50, long_peak_km=19, taper=(0.75,))),
    (float("inf"), Profile(weeks=16, peak_km=65, long_peak_km=32, taper=(0.8, 0.6))),
)


def profile_for(distance_km: float) -> Profile:
    return next(profile for limit, profile in PROFILES if distance_km <= limit)


def _km(value: float) -> int:
    return int(round_metric(value, 0))


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _planned_weeks(profile: Profile, total: int, base: float, long_base: float, distance: float) -> list[dict]:
    peak = max(base, min(profile.peak_km, base * MAX_PEAK_GROWTH))
    build_count = total - len(profile.taper) - 1
    weeks: list[dict] = []
    volume, long = base, long_base
    for index in range(build_count):
        recovery = index % RECOVERY_EVERY == RECOVERY_EVERY - 1 and index != build_count - 1
        if recovery:
            week_km, long_km = volume * RECOVERY_SHARE, long * RECOVERY_SHARE
        else:
            if index:
                volume = min(peak, volume * WEEKLY_GROWTH)
                long = min(profile.long_peak_km, max(long * WEEKLY_GROWTH, long + 1))
            long = min(long, volume * LONG_RUN_MAX_SHARE) if index else long
            week_km, long_km = volume, long
        race_pace = 0 if recovery or index < 2 else min(distance * 0.5, week_km * RACE_PACE_SHARE)
        weeks.append({"phase": "recovery" if recovery else "build", "km": _km(week_km),
                      "long_km": _km(long_km), "race_pace_km": _km(race_pace)})
    if weeks and weeks[-1]["phase"] == "build":
        weeks[-1]["phase"] = "peak"
    for share in profile.taper:
        week_km = peak * share
        weeks.append({"phase": "taper", "km": _km(week_km), "long_km": _km(long * share),
                      "race_pace_km": _km(min(distance * 0.3, week_km * RACE_PACE_SHARE))})
    weeks.append({"phase": "race", "km": _km(peak * RACE_WEEK_EASY_SHARE + distance),
                  "long_km": round_metric(distance, 1), "race_pace_km": 0})
    return weeks


def _status(week: dict, start: date, as_of: date) -> str:
    if start > as_of:
        return "upcoming"
    if start + timedelta(days=6) >= as_of:
        return "current"
    done_km = week["actual_km"] >= week["km"] * DONE_SHARE
    if done_km and week["actual_longest_km"] >= week["long_km"] * DONE_SHARE:
        return "done"
    return "partial" if week["actual_km"] >= week["km"] * PARTIAL_SHARE else "missed"


def build_plan(goal: dict, runs: list[tuple[date, float]], as_of: date) -> dict | None:
    """The weekly plan for `goal`, with each started week's actual distance; None after the race."""
    race_day = date.fromisoformat(goal["race_date"])
    if race_day < as_of:
        return None
    distance = float(goal["distance_km"])
    profile = profile_for(distance)
    total = goal.get("plan_weeks") or profile.weeks
    race_monday = _monday(race_day)
    start = race_monday - timedelta(weeks=total - 1)
    baseline_end = min(start, _monday(as_of))
    baseline_runs = [km for day, km in runs if baseline_end - timedelta(weeks=BASELINE_WEEKS) <= day < baseline_end]
    baseline = sum(baseline_runs) / BASELINE_WEEKS
    base = max(baseline, MIN_BASE_KM)
    long_base = max(MIN_LONG_KM, min(max(baseline_runs, default=0.0), base * LONG_RUN_MAX_SHARE))
    weeks = []
    for offset, planned in enumerate(_planned_weeks(profile, total, base, long_base, distance)):
        week_start = start + timedelta(weeks=offset)
        rows = [km for day, km in runs if week_start <= day < week_start + timedelta(days=7) and day <= as_of]
        week = {"week": offset + 1, "week_start": week_start.isoformat(), **planned,
                "actual_km": round_metric(sum(rows)), "actual_longest_km": round_metric(max(rows, default=0.0))}
        week["status"] = _status(week, week_start, as_of)
        weeks.append(week)
    longest_planned = max(week["long_km"] for week in weeks if week["phase"] != "race")
    long_threshold = round_metric(distance * LONG_RUN_SHARE, 1)
    return {
        "weeks_total": total,
        "weeks_chosen": goal.get("plan_weeks") is not None,
        "default_weeks": profile.weeks,
        "weeks_until_race": (race_monday - _monday(as_of)).days // 7 + 1,
        "start_date": start.isoformat(),
        "started": start <= as_of,
        "baseline_km": round_metric(baseline, 1),
        "baseline_start": (baseline_end - timedelta(weeks=BASELINE_WEEKS)).isoformat(),
        "baseline_end": (baseline_end - timedelta(days=1)).isoformat(),
        "peak_km": max(week["km"] for week in weeks if week["phase"] != "race"),
        "longest_planned_km": longest_planned,
        "long_threshold_km": long_threshold,
        "long_below_threshold": longest_planned < long_threshold,
        "weeks_done": sum(week["status"] == "done" for week in weeks),
        "weeks_past": sum(week["status"] in {"done", "partial", "missed"} for week in weeks),
        "weeks": weeks,
    }


def race_preparation(db: Session, user_id: int, as_of: date) -> dict:
    """Race readiness (SPEC-065) plus the weekly plan; `plan` is None without a goal or after the race."""
    readiness = race_readiness(db, user_id, as_of)
    goal = readiness["goal"]
    return {**readiness, "plan": None if goal is None else _race_plan(db, user_id, goal, as_of)}


def _race_plan(db: Session, user_id: int, goal: dict, as_of: date) -> dict | None:
    rows = (
        db.query(models.Run.date, models.Run.km)
        .filter(models.Run.user_id == user_id, TRAINING_RUN, models.Run.date <= as_of.isoformat())
        .all()
    )
    return build_plan(goal, [(date.fromisoformat(day), float(km)) for day, km in rows], as_of)
