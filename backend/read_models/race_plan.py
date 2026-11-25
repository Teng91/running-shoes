"""User-scoped weekly race training plan (SPEC-119).

The plan is a deterministic function of the race goal and the runner's own volume, so the
same data always gives the same plan and past weeks never move:

- The plan starts the runner's chosen number of weeks before race week (4–24, including race
  week); a goal saved without a choice stores `suggested_plan_weeks` (SPEC-125), so only goals
  saved before SPEC-125 may lack one and use the distance's default.
- Its baseline is the average weekly distance of the four weeks before the plan starts (or
  before this week, while the plan has not started), so it no longer changes once it starts.
- Build weeks grow at most 10% a week, every fourth week is a lighter recovery week, then the
  plan tapers into race week. The long run grows the same way, is at most half the week, and
  the last full long run ends at least two weeks before the race (as race readiness asks).
  A long run that already exceeds the distance's usual peak is kept, never cut (SPEC-122).
- A build week whose two previous weeks reached less than 60% of their distance starts again
  from what was actually run, and the weeks after it grow from there; weeks that already
  started keep their targets, so only the weeks ahead move (SPEC-123).
- Every week suggests how many runs to do in each intensity zone (SPEC-124): build weeks one
  race-pace run plus one faster (5K/10K) or steady (half/full) run, a single race-pace run in
  light weeks and below 25 km, nothing extra in race week; the rest is easy running.
- When the longest planned run stays below 75% of the race, the plan says which longer plan
  length or weekly base would reach it (SPEC-122).

Volume counts every training activity (`TRAINING_RUN`); the AI coach only explains the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.read_models.race_readiness import (
    LONG_RUN_SHARE,
    ZONES,
    goal_pace,
    race_readiness,
    zone_for,
)
from backend.read_models.rounding import round_metric
from backend.read_models.run_statistics import TRAINING_RUN
from backend.run_metrics import PACE_ACTIVITY_TYPES

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
RACE_WEEK_EASY_SHARE = 0.3
# A week counts as done at 90% of its distance and long run, as partly done at 60%.
DONE_SHARE = 0.9
PARTIAL_SHARE = 0.6
# A build week looks back at this many finished weeks before it adapts (SPEC-123).
ADAPT_WEEKS = 2


# Weeks below this distance get a single quality run (SPEC-124).
TWO_QUALITY_MIN_KM = 25

MIN_PLAN_WEEKS = 4
MAX_PLAN_WEEKS = 24
# The highest weekly base the long-run suggestion searches (SPEC-122).
MAX_SUGGESTED_BASE_KM = 150


@dataclass(frozen=True)
class Profile:
    weeks: int
    peak_km: int
    long_peak_km: int
    taper: tuple[float, ...]  # share of peak volume in each week between the build and race week
    second_quality: str  # the zone of a build week's second quality run (SPEC-124)


# Upper distance (km) for each profile: 5K, 10K, half and full marathon.
PROFILES = (
    (5.5, Profile(weeks=8, peak_km=30, long_peak_km=10, taper=(0.7,), second_quality="fast")),
    (10.5, Profile(weeks=10, peak_km=40, long_peak_km=14, taper=(0.7,), second_quality="fast")),
    (21.5, Profile(weeks=12, peak_km=50, long_peak_km=19, taper=(0.75,), second_quality="steady")),
    (float("inf"), Profile(weeks=16, peak_km=65, long_peak_km=32, taper=(0.8, 0.6), second_quality="steady")),
)


def profile_for(distance_km: float) -> Profile:
    return next(profile for limit, profile in PROFILES if distance_km <= limit)


def suggested_plan_weeks(distance_km: float, race_day: date, today: date) -> int:
    """The weeks left until race week, at most the distance's default (SPEC-125).

    A goal saved without a length stores this, as the race goal form does, so the plan start
    is fixed when the goal is saved instead of moving as the race comes closer.
    """
    weeks_until_race = (_monday(race_day) - _monday(today)).days // 7 + 1
    return max(MIN_PLAN_WEEKS, min(profile_for(distance_km).weeks, weeks_until_race))


def _km(value: float) -> int:
    return int(round_metric(value, 0))


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _adapted(weeks: list[dict], recent: list[tuple[float, float]], volume: float, long: float) -> tuple[float, float] | None:
    """Lower volume and long run to what was run when the last finished weeks fell short (SPEC-123)."""
    actual = sum(km for km, _ in recent)
    if actual >= sum(week["km"] for week in weeks[-ADAPT_WEEKS:]) * PARTIAL_SHARE:
        return None
    volume = min(volume, max(MIN_BASE_KM, actual / ADAPT_WEEKS))
    longest = max(MIN_LONG_KM, max(longest for _, longest in recent))
    return volume, min(long, longest, volume * LONG_RUN_MAX_SHARE)


def _planned_weeks(profile: Profile, total: int, base: float, long_base: float, distance: float,
                   finished: list[tuple[float, float]] | None = None) -> list[dict]:
    """Weekly targets; `finished` holds the (distance, longest run) of plan weeks that have ended.

    A build week decides on its Monday from finished weeks only, so a started week never moves.
    """
    finished = finished or []
    # Taper and race week follow the highest volume the plan reaches, so a short plan never
    # tapers above its own peak week (SPEC-121).
    peak = max(base, min(profile.peak_km, base * MAX_PEAK_GROWTH))
    # A long run already above the distance's usual peak is kept, never cut (SPEC-122).
    long_peak = max(profile.long_peak_km, long_base)
    build_count = total - len(profile.taper) - 1
    weeks: list[dict] = []
    volume, long = base, long_base
    # Weeks judged after an adjustment are both planned from it, so one shortfall lowers once.
    next_check = ADAPT_WEEKS
    for index in range(build_count):
        recovery = index % RECOVERY_EVERY == RECOVERY_EVERY - 1 and index != build_count - 1
        adapted = None
        if next_check <= index <= len(finished):
            adapted = _adapted(weeks, finished[index - ADAPT_WEEKS:index], volume, long)
        if adapted:
            volume, long = adapted
            next_check = index + ADAPT_WEEKS
        if recovery:
            week_km, long_km = volume * RECOVERY_SHARE, long * RECOVERY_SHARE
        else:
            if index and not adapted:
                volume = min(peak, volume * WEEKLY_GROWTH)
                long = min(long_peak, max(long * WEEKLY_GROWTH, long + 1))
            long = min(long, volume * LONG_RUN_MAX_SHARE) if index else long
            week_km, long_km = volume, long
        weeks.append({"phase": "recovery" if recovery else "build", "km": _km(week_km), "long_km": _km(long_km),
                      "adjusted": adapted is not None})
    if weeks and weeks[-1]["phase"] == "build":
        weeks[-1]["phase"] = "peak"
    for share in profile.taper:
        weeks.append({"phase": "taper", "km": _km(volume * share), "long_km": _km(long * share), "adjusted": False})
    weeks.append({"phase": "race", "km": _km(volume * RACE_WEEK_EASY_SHARE + distance),
                  "long_km": round_metric(distance, 1), "adjusted": False})
    return weeks


def _longest_planned(weeks: list[dict]) -> float:
    return max(week["long_km"] for week in weeks if week["phase"] != "race")


def _long_run_options(profile: Profile, total: int, base: float, long_base: float, distance: float,
                      threshold: float, weeks_until_race: int, started: bool) -> tuple[int | None, int | None]:
    """The shortest plan length and the lowest weekly base whose plan reaches `threshold` (SPEC-122).

    A longer plan is only offered while it can still start this week or later, and a higher base
    only before the plan starts, because a started plan keeps its baseline.
    """
    def reaches(weeks: int, weekly: float, long: float) -> bool:
        return _longest_planned(_planned_weeks(profile, weeks, weekly, long, distance)) >= threshold

    longer = next((weeks for weeks in range(total + 1, min(MAX_PLAN_WEEKS, weeks_until_race) + 1)
                   if reaches(weeks, base, long_base)), None)
    if started:
        return longer, None
    # A higher base keeps the runner's own long-run share of the week.
    share = long_base / base
    higher = next((weekly for weekly in range(int(base) + 1, MAX_SUGGESTED_BASE_KM + 1)
                   if reaches(total, weekly, max(MIN_LONG_KM, weekly * share))), None)
    return longer, higher


def _quality_runs(profile: Profile, week: dict) -> dict[str, int]:
    """Suggested runs per intensity zone for one week; the rest of the week is easy (SPEC-124)."""
    counts = {key: 0 for key, _, _, _ in ZONES}
    if week["phase"] == "race":
        return counts
    counts["race"] = 1
    if week["phase"] in {"build", "peak"} and week["km"] >= TWO_QUALITY_MIN_KM:
        counts[profile.second_quality] += 1
    return counts


def _zone_runs(timed_runs: list[tuple[date, float, int]], pace_goal: float) -> dict[str, int]:
    """Road runs with a time per intensity zone, the same zones as the readiness chart (SPEC-121)."""
    counts = {key: 0 for key, _, _, _ in ZONES}
    for _, km, seconds in timed_runs:
        counts[zone_for(seconds / km, pace_goal)] += 1
    return counts


def _status(week: dict, start: date, as_of: date) -> str:
    if start > as_of:
        return "upcoming"
    if start + timedelta(days=6) >= as_of:
        return "current"
    done_km = week["actual_km"] >= week["km"] * DONE_SHARE
    if done_km and week["actual_longest_km"] >= week["long_km"] * DONE_SHARE:
        return "done"
    return "partial" if week["actual_km"] >= week["km"] * PARTIAL_SHARE else "missed"


def build_plan(goal: dict, runs: list[tuple[date, float]], as_of: date,
               timed_runs: list[tuple[date, float, int]] | None = None) -> dict | None:
    """The weekly plan for `goal`, with each started week's actual distance; None after the race.

    `timed_runs` are the road runs with a time, counted per intensity zone in started weeks.
    """
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
    starts = [start + timedelta(weeks=offset) for offset in range(total)]
    actuals = []
    for week_start in starts:
        rows = [km for day, km in runs if week_start <= day <= min(week_start + timedelta(days=6), as_of)]
        actuals.append((round_metric(sum(rows)), round_metric(max(rows, default=0.0))))
    finished = [actual for week_start, actual in zip(starts, actuals, strict=True)
                if week_start + timedelta(days=6) < as_of]
    weeks = []
    planned_weeks = _planned_weeks(profile, total, base, long_base, distance, finished)
    for offset, (week_start, planned, (actual_km, longest)) in enumerate(zip(starts, planned_weeks, actuals, strict=True)):
        week_end = min(week_start + timedelta(days=6), as_of)
        timed = [run for run in timed_runs or [] if week_start <= run[0] <= week_end]
        week = {"week": offset + 1, "week_start": week_start.isoformat(), **planned,
                "quality_runs": _quality_runs(profile, planned), "actual_km": actual_km, "actual_longest_km": longest,
                "zone_runs": _zone_runs(timed, goal_pace(goal))}
        week["status"] = _status(week, week_start, as_of)
        weeks.append(week)
    longest_planned = _longest_planned(weeks)
    long_threshold = round_metric(distance * LONG_RUN_SHARE, 1)
    weeks_until_race = (race_monday - _monday(as_of)).days // 7 + 1
    longer, higher = (None, None)
    if longest_planned < long_threshold:
        longer, higher = _long_run_options(profile, total, base, long_base, distance, long_threshold,
                                           weeks_until_race, start <= as_of)
    return {
        "weeks_total": total,
        "weeks_chosen": goal.get("plan_weeks") is not None,
        "default_weeks": profile.weeks,
        "weeks_until_race": weeks_until_race,
        "start_date": start.isoformat(),
        "started": start <= as_of,
        "baseline_km": round_metric(baseline, 1),
        "baseline_start": (baseline_end - timedelta(weeks=BASELINE_WEEKS)).isoformat(),
        "baseline_end": (baseline_end - timedelta(days=1)).isoformat(),
        "peak_km": max(week["km"] for week in weeks if week["phase"] != "race"),
        "longest_planned_km": longest_planned,
        "long_threshold_km": long_threshold,
        "long_below_threshold": longest_planned < long_threshold,
        "long_weeks_needed": longer,
        "long_base_needed_km": higher,
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
        db.query(models.Run.date, models.Run.km, models.Run.duration_seconds, models.Run.activity_type)
        .filter(models.Run.user_id == user_id, TRAINING_RUN, models.Run.date <= as_of.isoformat())
        .all()
    )
    runs = [(date.fromisoformat(day), float(km)) for day, km, _, _ in rows]
    # Pace zones use road runs only, like race readiness (SPEC-096).
    timed = [(date.fromisoformat(day), float(km), seconds) for day, km, seconds, kind in rows
             if seconds and kind in PACE_ACTIVITY_TYPES]
    return build_plan(goal, runs, as_of, timed)
