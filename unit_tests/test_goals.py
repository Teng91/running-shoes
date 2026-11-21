"""Regression tests for per-user running goals and progress."""

from datetime import date

from fastapi.testclient import TestClient

from backend.credentials import get_password_hash
from backend.dependencies import get_db
from backend.main import app
from backend.models import Run, RunningGoal, Shoe, User
from backend.read_models import goal_progress
from unit_tests.token_helpers import token_for_name


def _headers(db, username: str) -> dict[str, str]:
    token = token_for_name(db, username)
    return {"Authorization": f"Bearer {token}"}


def test_goal_defaults_and_update_are_per_user(db):
    first = User(username="goal-a", hashed_password=get_password_hash("pass1234"))
    second = User(username="goal-b", hashed_password=get_password_hash("pass1234"))
    db.add_all([first, second])
    db.commit()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            default = client.get("/api/running-goal", headers=_headers(db, "goal-a"))
            assert default.json() == {
                "version": 0, "start_year": 2026,
                "monthly_km": 125.0, "yearly_km": 1500.0,
            }
            updated = client.put(
                "/api/running-goal", headers=_headers(db, "goal-a"),
                json={"start_year": 2027, "monthly_km": 130},
            )
            assert updated.status_code == 200
            assert updated.json()["version"] == 1
            assert updated.json()["monthly_km"] == 130.0
            assert client.get(
                "/api/running-goal", headers=_headers(db, "goal-b")
            ).json()["monthly_km"] == 125.0
            assert db.query(RunningGoal).count() == 1
    finally:
        app.dependency_overrides.clear()


def test_goal_update_rejects_non_positive_distance(db, user_with_token):
    _user, token = user_with_token

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/running-goal", headers={"Authorization": f"Bearer {token}"},
                json={"start_year": 2026, "monthly_km": 0},
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_goal_update_rejects_stale_version(db, user_with_token):
    _user, token = user_with_token

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            first = client.put(
                "/api/running-goal", headers=headers,
                json={"expected_version": 0, "start_year": 2026, "monthly_km": 130},
            )
            stale = client.put(
                "/api/running-goal", headers=headers,
                json={"expected_version": 0, "start_year": 2026, "monthly_km": 140},
            )
        assert first.status_code == 200
        assert first.json()["version"] == 1
        assert stale.status_code == 409
        assert goal_progress.goal_values(db, _user.id)["monthly_km"] == 130
    finally:
        app.dependency_overrides.clear()


def test_goal_progress_stops_ytd_at_requested_month(db, user_with_token):
    user, _token = user_with_token
    shoe = Shoe(user_id=user.id, brand="A", model="Goal", date="2026-01-01")
    db.add(shoe)
    db.flush()
    db.add_all([
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-15", km=100),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-02-05", km=125),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-03-01", km=500),
    ])
    db.commit()

    progress = goal_progress.goal_progress(db, user.id, 2026, 2, as_of=date(2026, 2, 10))

    assert progress["active"] is True
    assert progress["month_achievement_percent"] == 100.0
    assert progress["month_remaining_km"] == 0
    assert progress["month_state"] == "current"
    assert progress["remaining_days"] == 18
    assert progress["pace_delta_km"] == 80.36
    assert progress["required_daily_km"] == 0
    assert progress["ytd_km"] == 225.0
    assert progress["year_achievement_percent"] == 15.0


def _goal_runs(db, user, rows):
    shoe = Shoe(user_id=user.id, brand="A", model=f"Goal {user.id}", date="2025-01-01")
    db.add(shoe)
    db.flush()
    db.add_all(Run(user_id=user.id, shoe_id=shoe.id, date=day, km=km) for day, km in rows)


def test_year_goal_overview_marks_every_month_against_the_monthly_target(db, user_with_token):
    """SPEC-044: one annual view replaces the separate month picker."""
    from backend.models import MonthlyMileage
    from backend.read_models.trends import training_trends

    user, _token = user_with_token
    other = User(username="goal-other", hashed_password=get_password_hash("pass1234"))
    db.add(other)
    db.flush()
    _goal_runs(db, user, [
        ("2026-01-10", 130), ("2026-02-05", 100), ("2026-03-01", 60), ("2026-03-20", 65),
        ("2026-04-02", 20), ("2026-04-30", 50),  # the last run is after as_of and ignored
    ])
    _goal_runs(db, other, [("2026-02-10", 500)])
    db.add(MonthlyMileage(user_id=user.id, year=2026, month=2, km=400, adjustment_km=300))
    db.commit()
    as_of = date(2026, 4, 10)

    overview = goal_progress.year_goal_overview(db, user.id, 2026, as_of=as_of)

    months = overview["months"]
    assert [row["km"] for row in months] == [130, 100, 125, 20] + [0.0] * 8
    assert [row["state"] for row in months[:5]] == ["past", "past", "past", "current", "future"]
    assert [row["met"] for row in months[:4]] == [True, False, True, False]
    assert months[1]["percent"] == 80.0
    assert (overview["months_closed"], overview["months_met"]) == (3, 2)
    assert overview["year_state"] == "current" and overview["focus_month"] == 4
    assert overview["month_km"] == 20 and overview["month_state"] == "current"
    assert overview["ytd_km"] == 375
    # Day 100 of 365: the same pro-rata point the cumulative trend chart draws.
    assert overview["year_expected_km_to_date"] == 410.96
    assert overview["year_expected_km_to_date"] == training_trends(db, user.id, 2026, as_of)["cumulative"]["expected_km"]
    assert overview["year_pace_delta_km"] == -35.96
    assert overview["year_remaining_days"] == 265
    assert overview["required_weekly_km"] == 29.72


def test_year_goal_overview_handles_past_future_and_untracked_years(db, user_with_token):
    user, _token = user_with_token
    db.add(RunningGoal(user_id=user.id, start_year=2025, monthly_km=100, version=1))
    _goal_runs(db, user, [("2025-01-03", 120), ("2025-12-30", 80), ("2024-06-01", 200)])
    db.commit()
    as_of = date(2026, 4, 10)

    past = goal_progress.year_goal_overview(db, user.id, 2025, as_of=as_of)
    assert past["active"] is True and past["year_state"] == "past"
    assert past["focus_month"] == 12 and past["ytd_km"] == 200
    assert (past["months_closed"], past["months_met"]) == (12, 1)
    assert past["year_expected_km_to_date"] == 1200 and past["required_weekly_km"] is None

    future = goal_progress.year_goal_overview(db, user.id, 2027, as_of=as_of)
    assert future["year_state"] == "future" and future["ytd_km"] == 0
    assert {row["state"] for row in future["months"]} == {"future"}
    assert (future["months_closed"], future["months_met"]) == (0, 0)
    assert future["year_expected_km_to_date"] == 0 and future["required_weekly_km"] is None

    untracked = goal_progress.year_goal_overview(db, user.id, 2024, as_of=as_of)
    assert untracked["active"] is False
    assert untracked["months"][5]["km"] == 200
    assert not any(row["met"] for row in untracked["months"]) and untracked["months_met"] == 0


def test_year_goal_api_is_user_scoped(db):
    first = User(username="year-a", hashed_password=get_password_hash("pass1234"))
    second = User(username="year-b", hashed_password=get_password_hash("pass1234"))
    db.add_all([first, second])
    db.flush()
    _goal_runs(db, first, [("2026-01-05", 10)])
    _goal_runs(db, second, [("2026-01-06", 999)])
    db.commit()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/running-goal/year?year=2026", headers=_headers(db, "year-a"))
            assert response.status_code == 200
            assert response.json() == goal_progress.year_goal_overview(db, first.id, 2026)
            assert response.json()["months"][0]["km"] == 10
            assert client.get("/api/running-goal/year?year=1800", headers=_headers(db, "year-a")).status_code == 422
            assert client.get("/api/running-goal/year?year=2026").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_derived_yearly_goal_is_stored_returned_and_exported_at_two_decimals(db, user_with_token):
    """v4.7.1: 12.3 km/month is 147.6 km/year, never 147.60000000000002."""
    from backend.services.exports import build_account_export

    user, token = user_with_token

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            updated = client.put("/api/running-goal", headers={"Authorization": f"Bearer {token}"},
                                 json={"start_year": 2026, "monthly_km": 12.3})
            assert updated.status_code == 200
            assert updated.json()["yearly_km"] == 147.6
    finally:
        app.dependency_overrides.clear()
    db.expire_all()
    row = db.query(RunningGoal).filter_by(user_id=user.id).one()
    assert row.yearly_km == 147.6
    # A row written before the fix still exports and reports the clean value.
    row.yearly_km = 12.3 * 12
    db.commit()
    assert goal_progress.goal_values(db, user.id)["yearly_km"] == 147.6
    assert build_account_export(db, user)[0]["running_goal"]["yearly_km"] == 147.6
    assert goal_progress.yearly_goal_km(0.1) == 1.2
