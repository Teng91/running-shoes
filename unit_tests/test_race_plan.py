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
    assert all(week["race_pace_km"] == 0 for week in plan["weeks"] if week["phase"] in {"recovery", "race"})
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
    assert [(week["km"], week["long_km"]) for week in first] == [(20, 10), (22, 11), (24, 12), (19, 10)]
    assert [week["status"] for week in first] == ["done", "partial", "missed", "current"]
    assert [week["actual_km"] for week in first] == [20, 14, 5, 6]
    assert first[0]["actual_longest_km"] == 10
    assert (plan["weeks_done"], plan["weeks_past"]) == (1, 3)

    later = build_plan(goal, runs, date(2026, 12, 2))
    assert [week["km"] for week in later["weeks"]] == [week["km"] for week in plan["weeks"]], "the baseline is fixed"
    assert later["weeks"][3]["status"] == "missed"


def test_no_plan_after_the_race():
    assert build_plan(HALF, [], date(2027, 2, 22)) is None
    assert build_plan(HALF, [], date(2027, 2, 21))["weeks"][-1]["status"] == "current"


def test_race_analytics_include_a_user_scoped_plan_that_ignores_hikes(client, db):
    user, shoe = owner(db, "plan-owner")
    other, other_shoe = owner(db, "plan-other")
    db.add(RaceGoal(user_id=user.id, version=1, **{**HALF, "race_date": "2026-03-29"}))
    db.add(Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-01", km=12, activity_type="trail"))
    db.add(Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-02", km=40, activity_type="hike"))
    db.add(Run(user_id=other.id, shoe_id=other_shoe.id, date="2026-01-02", km=50))
    db.commit()

    # The plan starts Monday 2026-01-05; its baseline counts the trail run but not the hike.
    plan = race_preparation(db, user.id, date(2026, 1, 5))["plan"]
    assert (plan["start_date"], plan["started"], plan["baseline_km"]) == ("2026-01-05", True, 3)
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
