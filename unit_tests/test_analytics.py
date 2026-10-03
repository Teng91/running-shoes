from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import analytics
from backend.database import get_db
from backend.main import app
from backend.models import MonthlyMileage, Run, Shoe


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_shoe_analytics_combines_history_runs_training_and_cost(db, user_with_token):
    user, _token = user_with_token
    shoe = Shoe(
        user_id=user.id,
        brand="Mizuno",
        model="Wave Test",
        date="2026-01-01",
        price=600,
        mileage=130,
        baseline_mileage=100,
        expected_mileage=200,
        monthly_km=20,
    )
    db.add(shoe)
    db.flush()
    db.add_all([
        Run(
            user_id=user.id, shoe_id=shoe.id, date="2026-09-20", km=10,
        ),
        Run(
            user_id=user.id, shoe_id=shoe.id, date="2026-10-02", km=20,
        ),
    ])
    db.commit()

    result = analytics.shoe_analytics(db, user.id, shoe.id, today=date(2026, 10, 3))

    assert result is not None
    assert result["lifecycle"]["logged_mileage_km"] == 30
    assert result["lifecycle"]["historical_adjustment_km"] == 100
    assert result["lifecycle"]["reconciliation_difference_km"] == 0
    assert result["usage"]["count"] == 2
    assert "average_run_km" not in result["usage"]
    assert "average_pace_seconds_per_km" not in result["usage"]
    assert "average_rpe" not in result["usage"]
    assert result["usage"]["cost_per_wear"] == 300


def test_dashboard_flags_rotation_and_reports_goal_progress(db, user_with_token):
    user, _token = user_with_token
    primary = Shoe(
        user_id=user.id, brand="A", model="Primary", date="2026-01-01",
        mileage=90, baseline_mileage=60, expected_mileage=100,
    )
    backup = Shoe(user_id=user.id, brand="B", model="Backup", date="2026-01-01")
    db.add_all([primary, backup])
    db.flush()
    db.add_all([
        Run(user_id=user.id, shoe_id=primary.id, date="2026-10-01", km=10),
        Run(user_id=user.id, shoe_id=primary.id, date="2026-10-02", km=10),
        Run(user_id=user.id, shoe_id=primary.id, date="2026-10-03", km=10),
    ])
    db.add(MonthlyMileage(
        user_id=user.id, year=2026, month=10, km=30, adjustment_km=0,
    ))
    db.commit()

    result = analytics.dashboard_analytics(
        db, user.id, 2026, 10, today=date(2026, 10, 3)
    )

    assert result["month"]["km"] == 30
    assert result["shoe_usage"][0]["share_percent"] == 100
    assert result["goal"]["month_achievement_percent"] == 24
    assert {alert["type"] for alert in result["alerts"]} == {"lifecycle", "rotation"}


def test_manual_totals_become_explicit_adjustments_and_backup_is_private(
    client, db, user_with_token
):
    user, token = user_with_token
    create = client.post("/api/shoes", headers=_headers(token), json={
        "brand": "A", "model": "History", "date": "2026-01-01", "mileage": 50,
    })
    assert create.status_code == 200
    shoe_id = create.json()["id"]
    run = client.post("/api/runs", headers=_headers(token), json={
        "date": "2026-10-01", "km": 10, "shoe_id": shoe_id,
    })
    assert run.status_code == 200
    update = client.put(f"/api/shoes/{shoe_id}", headers=_headers(token), json={
        "mileage": 80, "expected_version": run.json().get("version", 1),
    })
    # A run update increments the shoe version; fetch the current version when
    # an older client encounters optimistic concurrency.
    if update.status_code == 409:
        current = client.get("/api/shoes/active", headers=_headers(token)).json()[0]
        update = client.put(f"/api/shoes/{shoe_id}", headers=_headers(token), json={
            "mileage": 80, "expected_version": current["version"],
        })
    assert update.status_code == 200
    assert update.json()["baseline_mileage"] == 70

    month = db.query(MonthlyMileage).filter_by(user_id=user.id, year=2026, month=10).one()
    assert month.km == 10
    assert month.adjustment_km == 0
    manual = client.put(f"/api/monthly-mileage/{month.id}", headers=_headers(token), json={"km": 25})
    assert manual.status_code == 200
    assert manual.json()["adjustment_km"] == 15

    backup = client.get("/api/export/account", headers=_headers(token))
    assert backup.status_code == 200
    assert "hashed_password" not in backup.text
    assert "access_token" not in backup.text
