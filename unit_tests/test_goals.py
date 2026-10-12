"""Regression tests for per-user running goals and progress."""

from datetime import date

from fastapi.testclient import TestClient

from backend import goals
from backend.auth import create_access_token, get_password_hash
from backend.database import get_db
from backend.main import app
from backend.models import MonthlyMileage, RunningGoal, User


def _headers(username: str) -> dict[str, str]:
    token = create_access_token(data={"sub": username})
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
            default = client.get("/api/running-goal", headers=_headers("goal-a"))
            assert default.json() == {
                "version": 0, "start_year": 2026,
                "monthly_km": 125.0, "yearly_km": 1500.0,
            }
            updated = client.put(
                "/api/running-goal", headers=_headers("goal-a"),
                json={"start_year": 2027, "monthly_km": 130},
            )
            assert updated.status_code == 200
            assert updated.json()["version"] == 1
            assert updated.json()["monthly_km"] == 130.0
            assert client.get(
                "/api/running-goal", headers=_headers("goal-b")
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
        assert goals.goal_values(db, _user.id)["monthly_km"] == 130
    finally:
        app.dependency_overrides.clear()


def test_goal_progress_stops_ytd_at_requested_month(db, user_with_token):
    user, _token = user_with_token
    db.add_all([
        MonthlyMileage(user_id=user.id, year=2026, month=1, km=100),
        MonthlyMileage(user_id=user.id, year=2026, month=2, km=125),
        MonthlyMileage(user_id=user.id, year=2026, month=3, km=500),
    ])
    db.commit()

    progress = goals.goal_progress(db, user.id, 2026, 2, as_of=date(2026, 2, 10))

    assert progress["active"] is True
    assert progress["month_achievement_percent"] == 100.0
    assert progress["month_remaining_km"] == 0
    assert progress["month_state"] == "current"
    assert progress["remaining_days"] == 18
    assert progress["pace_delta_km"] == 80.36
    assert progress["required_daily_km"] == 0
    assert progress["ytd_km"] == 225.0
    assert progress["year_achievement_percent"] == 15.0
