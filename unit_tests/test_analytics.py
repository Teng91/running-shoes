from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import analytics
from backend.dependencies import get_db
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
    assert result["usage"]["count"] == 2
    assert "average_run_km" not in result["usage"]
    assert "average_pace_seconds_per_km" not in result["usage"]
    assert "average_rpe" not in result["usage"]
    assert result["usage"]["cost_per_wear"] == 300


def test_dashboard_reports_lifecycle_alert_and_goal_progress(db, user_with_token):
    user, _token = user_with_token
    primary = Shoe(
        user_id=user.id, brand="A", model="Primary", date="2026-01-01",
        mileage=90, baseline_mileage=60, expected_mileage=100,
    )
    db.add(primary)
    db.flush()
    db.add_all([
        Run(user_id=user.id, shoe_id=primary.id, date="2026-10-01", km=10),
        Run(user_id=user.id, shoe_id=primary.id, date="2026-10-02", km=10),
        Run(user_id=user.id, shoe_id=primary.id, date="2026-10-03", km=10),
    ])
    db.add(MonthlyMileage(
        user_id=user.id, year=2026, month=10, km=130, adjustment_km=100,
    ))
    db.commit()

    result = analytics.dashboard_analytics(
        db, user.id, 2026, 10, today=date(2026, 10, 3)
    )

    assert result["month"]["km"] == 30
    assert result["shoe_usage"][0]["share_percent"] == 100
    assert result["goal"]["month_achievement_percent"] == 24
    assert result["goal"]["month_km"] == result["month"]["km"] == 30
    assert {alert["type"] for alert in result["alerts"]} == {"lifecycle"}
    assert "rotation" not in result


def test_dashboard_hides_soft_deleted_shoe_names_but_keeps_run_totals(
    db, user_with_token
):
    user, _token = user_with_token
    deleted = Shoe(
        user_id=user.id, brand="Hidden", model="History", date="2026-01-01",
        is_deleted=True,
    )
    db.add(deleted)
    db.flush()
    db.add(Run(user_id=user.id, shoe_id=deleted.id, date="2026-10-01", km=8))
    db.commit()

    result = analytics.dashboard_analytics(
        db, user.id, 2026, 10, today=date(2026, 10, 3)
    )

    assert result["month"]["km"] == 8
    assert result["shoe_usage"] == [{
        "shoe_id": deleted.id,
        "name": "鞋款已刪除",
        "km": 8.0,
        "count": 1,
        "share_percent": 100.0,
    }]


def test_dashboard_uses_same_period_comparison_and_future_month_is_empty(
    db, user_with_token
):
    user, _token = user_with_token
    shoe = Shoe(user_id=user.id, brand="A", model="One", date="2026-01-01")
    db.add(shoe)
    db.flush()
    db.add_all([
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-09-01", km=5),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-09-12", km=7),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-09-20", km=50),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-01", km=10),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-12", km=10),
        MonthlyMileage(user_id=user.id, year=2026, month=10, km=20),
    ])
    db.commit()

    current = analytics.dashboard_analytics(
        db, user.id, 2026, 10, today=date(2026, 10, 12)
    )
    future = analytics.dashboard_analytics(
        db, user.id, 2026, 11, today=date(2026, 10, 12)
    )

    assert current["comparison"] == {
        "label": "較上月同期",
        "through_day": 12,
        "current_km": 20.0,
        "previous_km": 12.0,
        "delta_km": 8.0,
    }
    assert current["forecast"]["projected_month_km"] == 51.67
    assert "consistency" not in current
    assert "year_activity" not in current
    assert "rotation" not in current
    assert future["comparison"]["label"] == "尚未開始"
    assert future["recent_7_days"]["state"] == "future"
    assert future["recent_7_days"]["km"] == 0
    assert future["forecast"]["state"] == "future"


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


def test_shoe_analytics_survives_legacy_extreme_forecast_values(db, user_with_token):
    user, _token = user_with_token
    shoe = Shoe(
        user_id=user.id,
        brand="Legacy",
        model="Extreme",
        date="2026-01-01",
        mileage=0,
        expected_mileage=1e12,
        monthly_km=0.01,
    )
    db.add(shoe)
    db.commit()

    result = analytics.shoe_analytics(db, user.id, shoe.id, today=date(2026, 10, 13))

    assert result is not None
    assert result["lifecycle"]["forecast_retirement_date"] is None


def test_shoe_analytics_sql_is_bounded_and_user_scoped(db, user_with_token):
    from datetime import timedelta

    from sqlalchemy import event

    from backend.models import User

    user, _ = user_with_token
    other = User(username="analytics-private", hashed_password="synthetic")
    db.add(other)
    db.flush()
    shoes = [Shoe(user_id=user.id, brand="Test", model=str(index), date="2025-01-01",
                  price=1000, mileage=500, expected_mileage=800, monthly_km=60)
             for index in range(3)]
    foreign = Shoe(user_id=other.id, brand="Private", model="Hidden", date="2025-01-01")
    deleted = Shoe(user_id=user.id, brand="Deleted", model="Hidden", date="2025-01-01", is_deleted=True)
    db.add_all([*shoes, foreign, deleted])
    db.flush()
    as_of = date(2026, 10, 23)
    records = []
    for shoe in shoes:
        for index in range(400):
            run = Run(user_id=user.id, shoe_id=shoe.id,
                      date=(as_of - timedelta(days=index // 2)).isoformat(), km=1.25 + index % 3)
            db.add(run)
            records.append(run)
        for when in ["2020-01-01", "2026-10-31", "2027-01-01"]:
            run = Run(user_id=user.id, shoe_id=shoe.id, date=when, km=7.75)
            db.add(run)
            records.append(run)
    db.add(Run(user_id=other.id, shoe_id=shoes[0].id, date="2026-10-22", km=9999))
    db.commit()
    # Warm attributes, then ensure read models never materialize even one Run entity.
    expected = [{"id": run.id, "shoe_id": run.shoe_id, "date": run.date, "km": run.km} for run in records]
    for shoe in [*shoes, foreign, deleted]:
        _ = shoe.id, shoe.user_id, shoe.is_deleted, shoe.price
    user_id = user.id
    for instance in list(db.identity_map.values()):
        if isinstance(instance, Run):
            db.expunge(instance)
    queries = []
    loaded = []

    def query(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)

    def load(_session, instance):
        if isinstance(instance, Run):
            loaded.append(instance)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", query)
    event.listen(db, "loaded_as_persistent", load)
    try:
        batch = analytics.batch_shoe_analytics(db, user_id, [*shoes, foreign, deleted], today=as_of)
        assert len(queries) == 3
        assert "row_number() OVER" in queries[-1]
        assert not loaded
        queries.clear()
        assert analytics.batch_shoe_analytics(db, user_id, [], today=as_of) == []
        assert not queries
    finally:
        event.remove(engine, "before_cursor_execute", query)
        event.remove(db, "loaded_as_persistent", load)
    assert [item["shoe"]["id"] for item in batch] == [shoe.id for shoe in shoes]
    for shoe, result in zip(shoes, batch, strict=True):
        rows = [run for run in expected if run["shoe_id"] == shoe.id]
        ordered = sorted(rows, key=lambda run: (run["date"], run["id"]), reverse=True)
        usage = result["usage"]
        assert usage["count"] == len(rows) == 403
        assert usage["km"] == sum(run["km"] for run in rows)
        assert usage["days"] == len({run["date"] for run in rows})
        assert usage["first_run_date"] == "2020-01-01"
        assert usage["last_run_date"] == "2027-01-01"
        for days in [30, 90]:
            start = (as_of - timedelta(days=days - 1)).isoformat()
            assert usage[f"km_{days}_days"] == sum(run["km"] for run in rows if start <= run["date"] <= as_of.isoformat())
        assert result["recent_runs"] == [{key: run[key] for key in ["id", "date", "km"]} for run in ordered[:12]]
        assert len(result["monthly_history"]) == 12
        assert result["monthly_history"][-1]["km"] == sum(run["km"] for run in rows if run["date"].startswith("2026-10"))
        assert analytics.shoe_analytics(db, user_id, shoe.id, today=as_of) == result
    assert analytics.shoe_analytics(db, user_id, foreign.id, today=as_of) is None
    assert analytics.shoe_analytics(db, user_id, deleted.id, today=as_of) is None


def test_shoe_analytics_empty_history_has_zero_metrics(db, user_with_token):
    user, _ = user_with_token
    shoe = Shoe(user_id=user.id, brand="Empty", model="Pair", date="2026-01-01")
    db.add(shoe)
    db.commit()
    result = analytics.shoe_analytics(db, user.id, shoe.id, today=date(2026, 1, 1))
    assert result["usage"]["km"] == result["usage"]["count"] == result["usage"]["days"] == 0
    assert result["usage"]["first_run_date"] is None
    assert result["usage"]["last_run_date"] is None
    assert result["usage"]["cost_per_wear"] is None
    assert result["recent_runs"] == []
    assert result["monthly_history"][0] == {"year": 2025, "month": 2, "km": 0, "count": 0}


def test_lifespan_thresholds_are_one_policy_for_alerts_status_and_frontend(db, user_with_token):
    """SPEC-055: watch from 80%, replace from 90% on every page, alert and tool."""
    from pathlib import Path

    from backend.read_models.shoes import list_my_shoes
    from backend.shoe_metrics import MONITOR_USAGE_PERCENT, REPLACE_SOON_USAGE_PERCENT

    user, _ = user_with_token
    for model, mileage in (("Worn", 760), ("Half", 680), ("Fresh", 632)):
        db.add(Shoe(user_id=user.id, brand="T", model=model, date="2026-01-01", mileage=mileage, expected_mileage=800))
    db.commit()
    alerts = analytics.dashboard_analytics(db, user.id, 2026, 10, today=date(2026, 10, 19))["alerts"]
    assert {alert["message"].split()[1]: alert["severity"] for alert in alerts} == {"Worn": "urgent", "Half": "warning"}
    statuses = {shoe["model"]: shoe["lifecycle_status"] for shoe in list_my_shoes(db, user.id)["shoes"]}
    assert statuses == {"Worn": "replace_soon", "Half": "monitor", "Fresh": "healthy"}
    state = Path("frontend/app-state.js").read_text(encoding="utf-8")
    assert f"const LIFECYCLE_MONITOR_PERCENT = {MONITOR_USAGE_PERCENT:g};" in state
    assert f"const LIFECYCLE_REPLACE_SOON_PERCENT = {REPLACE_SOON_USAGE_PERCENT:g};" in state
