"""SPEC-038 training trends and shoe rotation read models."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.credentials import get_password_hash
from backend.dependencies import get_db
from backend.main import app
from backend.models import Run, RunningGoal, Shoe, User
from backend.read_models.trends import shoe_timeline, training_trends
from unit_tests.token_helpers import create_access_token


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _shoe(db, user_id, **values):
    shoe = Shoe(user_id=user_id, brand=values.pop("brand", "Mizuno"), model=values.pop("model", "Sky"),
                date="2026-01-01", price=5000, mileage=0, expected_mileage=800, monthly_km=0, **values)
    db.add(shoe)
    db.flush()
    return shoe


def _runs(db, user_id, shoe_id, *rows):
    db.add_all(Run(user_id=user_id, shoe_id=shoe_id, date=day, km=km) for day, km in rows)
    db.commit()


def test_heatmap_merges_same_day_runs_and_counts_streaks(db, user_with_token):
    user, _ = user_with_token
    shoe = _shoe(db, user.id)
    _runs(db, user.id, shoe.id, ("2026-03-01", 5), ("2026-03-01", 3.5), ("2026-03-02", 10),
          ("2026-03-03", 4), ("2026-03-10", 6), ("2026-03-11", 6), ("2026-03-12", 6))

    result = training_trends(db, user.id, 2026, date(2026, 3, 13))

    assert result["daily"][0] == {"date": "2026-03-01", "km": 8.5}
    assert len(result["daily"]) == 6
    assert result["streaks"] == {"longest_days": 3, "longest_end": "2026-03-03", "current_days": 3}
    # A full day without a run ends the current streak.
    assert training_trends(db, user.id, 2026, date(2026, 3, 14))["streaks"]["current_days"] == 0


def test_weekly_load_flags_jump_over_previous_four_week_average(db, user_with_token):
    user, _ = user_with_token
    shoe = _shoe(db, user.id)
    # Four steady 20 km weeks (Mondays 2026-09-07 .. 09-28), then a 30 km week (+50%).
    _runs(db, user.id, shoe.id, ("2026-09-07", 20), ("2026-09-14", 20), ("2026-09-21", 20),
          ("2026-09-28", 20), ("2026-10-05", 30), ("2026-10-12", 25))

    weeks = training_trends(db, user.id, 2026, date(2026, 10, 14))["weekly"]

    assert len(weeks) == 16
    by_start = {week["week_start"]: week for week in weeks}
    assert by_start["2026-10-05"]["baseline_km"] == 20
    assert by_start["2026-10-05"]["change_percent"] == 50
    assert by_start["2026-10-05"]["spike"] is True
    # 25 km over a 22.5 km baseline is +11%: normal variation, not flagged.
    assert by_start["2026-10-12"]["spike"] is False
    assert by_start["2026-10-12"]["partial"] is True
    assert by_start["2026-10-05"]["partial"] is False
    # Tiny base weeks never flag, however large the percentage.
    assert by_start["2026-09-07"]["spike"] is False
    assert weeks[-1]["week_start"] == "2026-10-12"


def test_cumulative_goal_line_and_projection(db, user_with_token):
    user, _ = user_with_token
    db.add(RunningGoal(user_id=user.id, start_year=2026, monthly_km=100))
    shoe = _shoe(db, user.id)
    _runs(db, user.id, shoe.id, ("2026-01-01", 10), ("2026-01-10", 20))

    cumulative = training_trends(db, user.id, 2026, date(2026, 1, 10))["cumulative"]

    assert cumulative["yearly_goal_km"] == 1200
    assert len(cumulative["goal_km"]) == 365 and cumulative["goal_km"][-1] == 1200
    assert len(cumulative["actual_km"]) == 10
    assert cumulative["actual_km"][0] == 10 and cumulative["actual_km"][-1] == 30
    assert cumulative["expected_km"] == round(1200 * 10 / 365, 2)
    assert cumulative["delta_km"] == round(30 - 1200 * 10 / 365, 2)
    assert cumulative["projected_km"] == round(30 / 10 * 365, 2)


def test_future_year_is_empty_and_past_year_is_complete(db, user_with_token):
    user, _ = user_with_token
    shoe = _shoe(db, user.id)
    _runs(db, user.id, shoe.id, ("2025-12-31", 12))

    future = training_trends(db, user.id, 2027, date(2026, 5, 1))
    assert future["end_date"] is None and future["daily"] == [] and future["weekly"] == []
    past = training_trends(db, user.id, 2025, date(2026, 5, 1))
    assert past["end_date"] == "2025-12-31"
    assert len(past["cumulative"]["actual_km"]) == 365
    assert past["cumulative"]["ytd_km"] == 12


def test_shoe_timeline_orders_rotation_and_flags_idle_active_shoes(db, user_with_token):
    user, _ = user_with_token
    old = _shoe(db, user.id, model="Old", is_retired=True)
    idle = _shoe(db, user.id, model="Idle")
    daily = _shoe(db, user.id, model="Daily")
    deleted = _shoe(db, user.id, model="Gone", is_deleted=True)
    _shoe(db, user.id, model="Unworn")
    _runs(db, user.id, old.id, ("2025-01-01", 10), ("2025-08-01", 5))
    _runs(db, user.id, idle.id, ("2025-06-01", 8), ("2026-03-01", 8))
    _runs(db, user.id, daily.id, ("2026-02-01", 7), ("2026-04-28", 9))
    _runs(db, user.id, deleted.id, ("2024-01-01", 3))

    result = shoe_timeline(db, user.id, date(2026, 5, 1))

    # Retired, deleted and never-worn shoes are not in rotation.
    assert [row["shoe_id"] for row in result["shoes"]] == [idle.id, daily.id]
    rows = {row["shoe_id"]: row for row in result["shoes"]}
    assert rows[idle.id]["idle"] is True and rows[idle.id]["days_since_last_run"] == 61
    assert rows[daily.id] == {
        "shoe_id": daily.id, "first_run_date": "2026-02-01",
        "last_run_date": "2026-04-28", "km": 16, "run_count": 2, "days_since_last_run": 3, "idle": False,
    }


def test_trend_endpoints_are_user_scoped(client, db, user_with_token):
    user, token = user_with_token
    other = User(username="other", hashed_password=get_password_hash("pass1234"))
    db.add(other)
    db.commit()
    mine, theirs = _shoe(db, user.id), _shoe(db, other.id)
    _runs(db, user.id, mine.id, ("2026-01-05", 5))
    _runs(db, other.id, theirs.id, ("2026-01-06", 42))
    headers = {"Authorization": f"Bearer {token}"}

    trends = client.get("/api/analytics/trends?year=2026", headers=headers).json()
    timeline = client.get("/api/analytics/shoe-timeline", headers=headers).json()

    assert [row["date"] for row in trends["daily"]] == ["2026-01-05"]
    assert [row["shoe_id"] for row in timeline["shoes"]] == [mine.id]
    other_headers = {"Authorization": f"Bearer {create_access_token(data={'sub': 'other'})}"}
    other_trends = client.get("/api/analytics/trends?year=2026", headers=other_headers).json()
    assert [row["km"] for row in other_trends["daily"]] == [42]
    assert client.get("/api/analytics/trends?year=2026").status_code == 401
    assert client.get("/api/analytics/trends?year=1800", headers=headers).status_code == 422


def test_weekly_goal_longest_run_and_weekday_mix(db, user_with_token):
    """SPEC-056: the weekly target follows the annual goal line; each week has its longest run."""
    user, _ = user_with_token
    db.add(RunningGoal(user_id=user.id, start_year=2026, monthly_km=100))
    shoe = _shoe(db, user.id)
    # Monday 10-05 has two runs (25 km, longest 15); Saturday 10-10 a 21.1 km long run.
    _runs(db, user.id, shoe.id, ("2025-12-29", 9), ("2026-10-05", 10), ("2026-10-05", 15),
          ("2026-10-10", 21.1), ("2026-10-12", 5))

    result = training_trends(db, user.id, 2026, date(2026, 10, 14))

    assert result["weekly_goal"] == {"active": True, "km": round(1200 * 7 / 365, 2)}
    weeks = {week["week_start"]: week for week in result["weekly"]}
    assert (weeks["2026-10-05"]["km"], weeks["2026-10-05"]["longest_km"], weeks["2026-10-05"]["goal_met"]) == (46.1, 21.1, True)
    assert (weeks["2026-10-12"]["longest_km"], weeks["2026-10-12"]["goal_met"]) == (5, False)
    assert weeks["2026-09-28"]["longest_km"] == 0
    weekday = result["weekday"]
    assert [row["weekday"] for row in weekday] == list(range(7))
    # The 2025-12-29 Monday belongs to the previous year and is not counted.
    # Two runs on Monday 10-05 count as two runs on one running day (v4.14.1).
    assert weekday[0] == {"weekday": 0, "km": 30, "run_days": 2, "runs": 3, "pace": None}
    assert weekday[5] == {"weekday": 5, "km": 21.1, "run_days": 1, "runs": 1, "pace": None}
    assert sum(row["run_days"] for row in weekday) == 3

    before_goal = training_trends(db, user.id, 2025, date(2026, 10, 14))
    assert before_goal["weekly_goal"]["active"] is False
    assert not any(week["goal_met"] for week in before_goal["weekly"])
    future = training_trends(db, user.id, 2027, date(2026, 10, 14))
    assert future["weekday"] == [{"weekday": day, "km": 0, "run_days": 0, "runs": 0, "pace": None} for day in range(7)]
