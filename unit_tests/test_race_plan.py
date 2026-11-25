"""SPEC-119: deterministic weekly race training plan built from the runner's own volume."""

import json
from datetime import date, timedelta

from backend import agent_planner, agent_tools
from backend.clock import local_today
from backend.models import RaceGoal, Run
from backend.read_models.race_plan import build_plan, profile_for, race_preparation
from backend.tools import db_tools
from unit_tests.test_run_pace import client, headers, owner

__all__ = ["client"]

HALF = {"race_name": "示範半馬", "race_date": "2027-02-21", "distance_km": 21.0975, "target_seconds": 7200,
        "reference_distance_km": None, "reference_seconds": None, "reference_temperature_c": None}


def weekly_runs(start: date, end: date, weekly_km: float) -> list[tuple[date, float]]:
    """Tuesday and Thursday a quarter of the week each, Sunday the other half."""
    runs, day = [], start
    while day < end:
        if day.weekday() in (1, 3):
            runs.append((day, weekly_km * 0.25))
        elif day.weekday() == 6:
            runs.append((day, weekly_km * 0.5))
        day += timedelta(days=1)
    return runs


def test_plan_builds_from_the_baseline_with_recovery_taper_and_race_week():
    plan = build_plan(HALF, weekly_runs(date(2026, 9, 1), date(2026, 11, 26), 30), date(2026, 11, 25))

    assert profile_for(21.0975).weeks == plan["weeks_total"] == len(plan["weeks"]) == 12
    assert (plan["start_date"], plan["started"]) == ("2026-11-30", False)
    assert (plan["baseline_km"], plan["baseline_start"], plan["baseline_end"]) == (30, "2026-10-26", "2026-11-22")
    assert [week["phase"] for week in plan["weeks"]] == [
        "build", "build", "build", "recovery", "build", "build", "build", "recovery", "build", "peak", "taper", "race"]
    assert [week["km"] for week in plan["weeks"]] == [30, 33, 36, 29, 40, 44, 45, 36, 45, 45, 34, 35]
    assert [week["long_km"] for week in plan["weeks"]] == [15, 17, 18, 15, 19, 19, 19, 15, 19, 19, 14, 21.1]
    assert plan["peak_km"] == 45, "peak volume is at most 50% above the baseline"
    assert (plan["longest_planned_km"], plan["long_threshold_km"], plan["long_below_threshold"]) == (19, 15.8, False)
    # Build weeks grow by at most 10%; the long run is never more than half the week.
    for previous, week in zip(plan["weeks"], plan["weeks"][1:], strict=False):
        if week["phase"] in {"build", "peak"} and previous["phase"] in {"build", "peak"}:
            assert week["km"] <= previous["km"] * 1.1 + 0.5
    assert all(week["long_km"] <= week["km"] / 2 + 0.5 for week in plan["weeks"] if week["phase"] != "race")
    assert all(week["status"] == "upcoming" for week in plan["weeks"])


def test_a_beginner_gets_a_floor_and_a_warning_that_long_runs_stay_short():
    plan = build_plan({**HALF, "race_date": "2027-03-21", "distance_km": 42.195}, [], date(2026, 11, 25))
    assert plan["weeks_total"] == 16 and plan["baseline_km"] == 0
    assert plan["weeks"][0]["km"] == 15 and plan["weeks"][0]["long_km"] == 5
    assert plan["long_below_threshold"] is True and plan["longest_planned_km"] < plan["long_threshold_km"]
    assert [week["phase"] for week in plan["weeks"][-3:]] == ["taper", "taper", "race"]


def test_started_weeks_compare_actual_distance_and_past_weeks_never_move():
    goal = {**HALF, "race_date": "2026-12-27", "distance_km": 10}  # 10 weeks from Monday 2026-10-19
    runs = weekly_runs(date(2026, 9, 1), date(2026, 10, 19), 20)
    runs += [(date(2026, 10, 21), 10), (date(2026, 10, 25), 10)]   # week 1: 20 of 20 km, long 10 → done
    runs += [(date(2026, 10, 27), 14)]                              # week 2: 14 of 22 km → partial
    runs += [(date(2026, 11, 4), 5)]                                # week 3: 5 of 24 km → missed
    runs += [(date(2026, 11, 10), 6), (date(2026, 11, 30), 30)]     # current week; a future run is ignored
    plan = build_plan(goal, runs, date(2026, 11, 11))

    assert (plan["start_date"], plan["started"], plan["baseline_km"]) == ("2026-10-19", True, 20)
    first = plan["weeks"][:4]
    # Weeks 2 and 3 reached 19 of 46 km, so the current week starts again from 15 km (SPEC-123).
    assert [(week["km"], week["long_km"]) for week in first] == [(20, 10), (22, 11), (24, 12), (12, 6)]
    assert [week["adjusted"] for week in first] == [False, False, False, True]
    assert [week["status"] for week in first] == ["done", "partial", "missed", "current"]
    assert [week["actual_km"] for week in first] == [20, 14, 5, 6]
    assert first[0]["actual_longest_km"] == 10
    assert (plan["weeks_done"], plan["weeks_past"]) == (1, 3)

    later = build_plan(goal, runs, date(2026, 12, 2))
    assert later["baseline_km"] == 20, "the baseline is fixed"
    assert [week["km"] for week in later["weeks"][:4]] == [week["km"] for week in first], "started weeks never move"
    assert later["weeks"][3]["status"] == "missed"


def test_weeks_ahead_restart_from_what_was_run_after_a_shortfall():
    # SPEC-123: ten weeks before a 10K (from Monday 2026-10-19) on 20 km weeks.
    goal = {**HALF, "race_date": "2026-12-27", "distance_km": 10}
    runs = weekly_runs(date(2026, 9, 1), date(2026, 10, 26), 20)
    before = build_plan(goal, runs, date(2026, 10, 28))
    assert [week["km"] for week in before["weeks"]] == [20, 22, 24, 19, 27, 29, 30, 30, 21, 19]
    assert not any(week["adjusted"] for week in before["weeks"])

    # Week 2 ran nothing, so on its Monday week 3 starts again from the 15 km floor.
    stopped = [*runs, (date(2026, 11, 3), 6), (date(2026, 11, 7), 6)]
    plan = build_plan(goal, stopped, date(2026, 11, 3))
    assert [(week["km"], week["long_km"], week["adjusted"]) for week in plan["weeks"][:5]] == [
        (20, 10, False), (22, 11, False), (15, 8, True), (12, 6, False), (17, 8, False)]
    assert plan["weeks"][2]["status"] == "current"
    assert plan["weeks"][-2]["km"] < before["weeks"][-2]["km"], "taper and race week follow the lower volume"

    # Running the lowered weeks keeps the plan growing from there; one gap lowers it only once.
    back = [*stopped, (date(2026, 11, 12), 6), (date(2026, 11, 15), 6), (date(2026, 11, 18), 8), (date(2026, 11, 22), 9)]
    resumed = build_plan(goal, back, date(2026, 11, 25))
    assert [week["status"] for week in resumed["weeks"][2:5]] == ["partial", "done", "done"]
    assert [(week["km"], week["adjusted"]) for week in resumed["weeks"][2:6]] == [(15, True), (12, False), (17, False), (18, False)]
    assert [week["km"] for week in resumed["weeks"][:3]] == [week["km"] for week in plan["weeks"][:3]], "started weeks never move"

def test_the_runner_chooses_how_many_weeks_the_plan_lasts():
    # Seven weeks before a half marathon: the default 12-week plan began five weeks ago.
    as_of = date(2027, 1, 6)
    default = build_plan(HALF, [], as_of)
    assert (default["weeks_total"], default["weeks_chosen"], default["default_weeks"]) == (12, False, 12)
    assert (default["start_date"], default["weeks_until_race"]) == ("2026-11-30", 7)
    chosen = build_plan({**HALF, "plan_weeks": 7}, [], as_of)
    assert (chosen["weeks_total"], chosen["weeks_chosen"], chosen["start_date"]) == (7, True, "2027-01-04")
    assert [week["phase"] for week in chosen["weeks"]] == [
        "build", "build", "build", "recovery", "peak", "taper", "race"]
    assert chosen["weeks"][0]["status"] == "current"
    full = build_plan({**HALF, "distance_km": 42.195, "plan_weeks": 4}, [], as_of)
    assert [week["phase"] for week in full["weeks"]] == ["peak", "taper", "taper", "race"]


def test_plan_weeks_are_saved_with_the_goal(client, db):
    user, _ = owner(db, "plan-weeks")
    saved = client.put("/api/race-goal", headers=headers(user), json={**HALF, "race_date": "2099-06-07", "plan_weeks": 9})
    assert saved.status_code == 200, saved.text
    assert saved.json()["plan_weeks"] == 9
    assert client.get("/api/race-goal", headers=headers(user)).json()["plan_weeks"] == 9
    assert race_preparation(db, user.id, date(2099, 4, 1))["plan"]["weeks_total"] == 9


def test_a_short_plan_never_tapers_above_its_own_peak_and_counts_zones():
    # SPEC-121: four weeks before a half marathon from 33 km a week (the reported plan).
    goal = {**HALF, "race_date": "2026-12-06", "plan_weeks": 4}
    runs = weekly_runs(date(2026, 10, 12), date(2026, 11, 9), 33)
    goal_pace = HALF["target_seconds"] / HALF["distance_km"]  # 341 s/km
    timed = [(date(2026, 11, 10), 10, round(10 * (goal_pace + 60))),   # easy
             (date(2026, 11, 12), 8, round(8 * (goal_pace + 20))),     # steady
             (date(2026, 11, 15), 16, round(16 * goal_pace)),          # race pace
             (date(2026, 11, 13), 5, round(5 * (goal_pace - 30))),     # fast
             (date(2026, 11, 26), 6, round(6 * (goal_pace + 60)))]     # after as_of: ignored
    plan = build_plan(goal, runs, date(2026, 11, 25), timed)
    assert [(week["phase"], week["km"]) for week in plan["weeks"]] == [
        ("build", 33), ("peak", 36), ("taper", 27), ("race", 32)]
    peak = max(week["km"] for week in plan["weeks"] if week["phase"] in {"build", "peak"})
    assert all(week["km"] < peak for week in plan["weeks"] if week["phase"] == "taper")
    assert plan["weeks"][0]["zone_runs"] == {"easy": 1, "steady": 1, "race": 1, "fast": 1}
    assert plan["weeks"][2]["zone_runs"] == {"easy": 0, "steady": 0, "race": 0, "fast": 0}
    assert "race_pace_km" not in plan["weeks"][0]


def test_no_plan_after_the_race():
    assert build_plan(HALF, [], date(2027, 2, 22)) is None
    assert build_plan(HALF, [], date(2027, 2, 21))["weeks"][-1]["status"] == "current"


def test_race_analytics_include_a_user_scoped_plan_that_ignores_hikes(client, db):
    user, shoe = owner(db, "plan-owner")
    other, other_shoe = owner(db, "plan-other")
    db.add(RaceGoal(user_id=user.id, version=1, **{**HALF, "race_date": "2026-03-29"}))
    db.add(Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-01", km=12, activity_type="trail"))
    # Zones count timed road runs only: this timed trail run in week 1 is not counted.
    db.add(Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-06", km=10, duration_seconds=3600, activity_type="trail"))
    db.add(Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-07", km=10, duration_seconds=4000))
    db.add(Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-02", km=40, activity_type="hike"))
    db.add(Run(user_id=other.id, shoe_id=other_shoe.id, date="2026-01-02", km=50))
    db.commit()

    # The plan starts Monday 2026-01-05; its baseline counts the trail run but not the hike.
    assert race_preparation(db, user.id, date(2026, 1, 5))["plan"]["baseline_km"] == 3
    plan = race_preparation(db, user.id, date(2026, 1, 8))["plan"]
    assert (plan["start_date"], plan["started"], plan["baseline_km"]) == ("2026-01-05", True, 3)
    assert plan["weeks"][0]["zone_runs"] == {"easy": 1, "steady": 0, "race": 0, "fast": 0}
    assert plan["weeks"][0]["actual_km"] == 20, "the trail run still counts toward distance"
    response = client.get("/api/analytics/race", headers=headers(user)).json()
    assert response["goal"]["race_date"] == "2026-03-29"
    assert response["plan"] is None, "the race is over by the real date"
    assert client.get("/api/analytics/race", headers=headers(other)).json()["plan"] is None


def test_race_training_plan_tool_reads_the_same_plan(db):
    user, shoe = owner(db, "plan-tool")
    empty = json.loads(db_tools.race_training_plan(db, user.id))
    assert (empty["ok"], empty["goal"]) == (True, None) and "設定比賽" in empty["message"]

    race_day = local_today() + timedelta(weeks=6)
    db.add(RaceGoal(user_id=user.id, version=1, **{**HALF, "race_date": race_day.isoformat()}))
    db.add(Run(user_id=user.id, shoe_id=shoe.id, date=(local_today() - timedelta(days=10)).isoformat(), km=12))
    db.commit()
    result = json.loads(agent_tools.execute_tool("race_training_plan", {}, db, user.id))
    expected = race_preparation(db, user.id, local_today())
    assert result["tool"] == "race_training_plan" and result["plan"] == expected["plan"]
    assert result["plan"]["weeks"][-1]["phase"] == "race" and "plan.weeks.status" in result["field_definitions"]
    assert "intensity" not in result and len(result["intensity_zones"]) == 4
    assert agent_planner.build_query_plan("我的半馬課表這週要跑多少？").database_tools == ("race_training_plan",)
    assert "race_training_plan" in {tool["function"]["name"] for tool in db_tools.TOOL_DEFINITIONS}


def test_an_experienced_runner_keeps_a_long_run_above_the_distance_peak():
    # SPEC-122: 40 km weeks with a 20 km Sunday long run, ten weeks before a 10K (long peak 14).
    goal = {**HALF, "race_date": "2027-02-07", "distance_km": 10}
    plan = build_plan(goal, weekly_runs(date(2026, 10, 1), date(2026, 11, 25), 40), date(2026, 11, 25))
    build = [week for week in plan["weeks"] if week["phase"] in {"build", "peak"}]
    assert [week["long_km"] for week in build] == [20] * len(build), "the long run is never cut to 14 km"
    assert plan["long_below_threshold"] is False
    assert (plan["long_weeks_needed"], plan["long_base_needed_km"]) == (None, None)


def test_a_short_long_run_says_which_plan_length_or_base_reaches_it():
    as_of = date(2026, 11, 25)
    full = {**HALF, "distance_km": 42.195}
    # A beginner sixteen weeks out: only a 42 km base gets the long run to 75% of the marathon.
    beginner = build_plan({**full, "race_date": "2027-03-21"}, [], as_of)
    assert (beginner["longest_planned_km"], beginner["long_threshold_km"]) == (11, 31.6)
    assert (beginner["long_weeks_needed"], beginner["long_base_needed_km"]) == (None, 42)
    # An 8-week plan from 44 km weeks stops at 29 km; 9 weeks or a 48 km base reach 31.6 km.
    runs = weekly_runs(date(2026, 10, 1), date(2026, 11, 25), 44)
    short = build_plan({**full, "race_date": "2027-06-20", "plan_weeks": 8}, runs, as_of)
    assert (short["longest_planned_km"], short["weeks_until_race"]) == (29, 30)
    assert (short["long_weeks_needed"], short["long_base_needed_km"]) == (9, 48)
    assert build_plan({**full, "race_date": "2027-06-20", "plan_weeks": 9}, runs, as_of)["long_below_threshold"] is False
    # A started plan keeps its baseline and cannot start earlier, so it offers neither.
    started = build_plan({**full, "race_date": "2026-12-20", "plan_weeks": 8}, [], as_of)
    assert started["started"] and started["long_below_threshold"]
    assert (started["long_weeks_needed"], started["long_base_needed_km"]) == (None, None)
