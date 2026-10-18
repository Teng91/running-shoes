from contextlib import contextmanager
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.database import get_db
from backend.main import app
from backend.models import MonthlyMileage, Run
from backend.routers.reports import _local_today


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def _client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    original_engine = app.state.db_engine
    original_session = app.state.session_factory
    app.state.db_engine = db.get_bind()
    app.state.session_factory = sessionmaker(bind=db.get_bind())
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.state.db_engine = original_engine
        app.state.session_factory = original_session


def test_logged_month_cannot_move_and_totals_cannot_drop_below_logs(
    db, user_with_token
):
    user, token = user_with_token
    with _client(db) as client:
        shoe = client.post("/api/shoes", headers=_headers(token), json={
            "brand": "A", "model": "Safe", "date": "2026-01-01",
        }).json()
        run = client.post("/api/runs", headers=_headers(token), json={
            "date": "2026-08-02", "km": 8, "shoe_id": shoe["id"],
        })
        assert run.status_code == 200
        month = db.query(MonthlyMileage).filter_by(
            user_id=user.id, year=2026, month=8
        ).one()
        move = client.put(
            f"/api/monthly-mileage/{month.id}", headers=_headers(token),
            json={"expected_version": month.version, "month": 9},
        )
        lower_month = client.put(
            f"/api/monthly-mileage/{month.id}", headers=_headers(token),
            json={"expected_version": month.version, "km": 7},
        )
        current_shoe = client.get("/api/shoes/active", headers=_headers(token)).json()[0]
        lower_shoe = client.put(
            f"/api/shoes/{shoe['id']}", headers=_headers(token),
            json={"expected_version": current_shoe["version"], "mileage": 7},
        )

    app.dependency_overrides.clear()
    assert move.status_code == 400
    assert lower_month.status_code == 400
    assert lower_shoe.status_code == 400
    assert db.query(Run).filter_by(user_id=user.id).one().date == "2026-08-02"
    assert db.query(MonthlyMileage).filter_by(user_id=user.id).one().month == 8


def test_pure_manual_month_can_move(db, user_with_token):
    user, token = user_with_token
    manual = MonthlyMileage(
        user_id=user.id, year=2026, month=8, km=12, adjustment_km=12
    )
    db.add(manual)
    db.commit()
    with _client(db) as client:
        moved = client.put(
            f"/api/monthly-mileage/{manual.id}", headers=_headers(token),
            json={"expected_version": manual.version, "month": 9, "km": 15},
        )
        assert moved.status_code == 200

    app.dependency_overrides.clear()
    db.expire_all()
    updated = db.query(MonthlyMileage).filter_by(user_id=user.id).one()
    assert (updated.year, updated.month, updated.km, updated.adjustment_km) == (
        2026, 9, 15, 15
    )


def test_numeric_inputs_are_two_decimal_and_future_runs_are_rejected(
    db, user_with_token
):
    _user, token = user_with_token
    today = _local_today()
    with _client(db) as client:
        shoe_response = client.post("/api/shoes", headers=_headers(token), json={
            "brand": "Round",
            "model": "Values",
            "date": today.isoformat(),
            "price": 123.456,
            "mileage": 10.005,
            "expected_mileage": 800.004,
        })
        assert shoe_response.status_code == 200
        shoe = shoe_response.json()
        assert shoe["price"] == 123.46
        assert shoe["mileage"] == 10.01
        assert shoe["expected_mileage"] == 800.0

        run = client.post("/api/runs", headers=_headers(token), json={
            "date": today.isoformat(), "km": 1.235, "shoe_id": shoe["id"],
        })
        assert run.status_code == 200
        assert run.json()["km"] == 1.24

        subcent = client.post("/api/runs", headers=_headers(token), json={
            "date": today.isoformat(), "km": 0.004, "shoe_id": shoe["id"],
        })
        future = client.post("/api/runs", headers=_headers(token), json={
            "date": (today + timedelta(days=1)).isoformat(),
            "km": 1,
            "shoe_id": shoe["id"],
        })
        extreme = client.post("/api/shoes", headers=_headers(token), json={
            "brand": "Too",
            "model": "Large",
            "date": today.isoformat(),
            "expected_mileage": 1_000_000.01,
        })

    assert subcent.status_code == 422
    assert future.status_code == 422
    assert extreme.status_code == 422
