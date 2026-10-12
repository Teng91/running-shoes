from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend import analytics
from backend import main as main_module
from backend.auth import create_access_token, get_password_hash
from backend.database import get_db
from backend.main import app
from backend.models import MonthlyMileage, Run, Shoe, User


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def _client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    original_engine = main_module.engine
    original_session = main_module.SessionLocal
    main_module.engine = db.get_bind()
    main_module.SessionLocal = sessionmaker(bind=db.get_bind())
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        main_module.engine = original_engine
        main_module.SessionLocal = original_session


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


def test_pure_manual_month_can_move_and_edit_can_be_undone(db, user_with_token):
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
        operation = client.get("/api/operations", headers=_headers(token)).json()[0]
        undone = client.post(
            f"/api/operations/{operation['id']}/undo", headers=_headers(token), json={}
        )
        assert undone.status_code == 200

    app.dependency_overrides.clear()
    db.expire_all()
    restored = db.query(MonthlyMileage).filter_by(user_id=user.id).one()
    assert (restored.year, restored.month, restored.km, restored.adjustment_km) == (
        2026, 8, 12, 12
    )


def test_repair_rebuilds_invalid_and_missing_aggregates(db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(
        user_id=user.id, brand="A", model="Broken", date="2026-01-01",
        mileage=2, baseline_mileage=-3,
    )
    db.add(shoe)
    db.flush()
    db.add(Run(user_id=user.id, shoe_id=shoe.id, date="2026-08-02", km=5))
    db.commit()
    assert analytics.mileage_reconciliation(db, user.id)["ok"] is False

    with _client(db) as client:
        repaired = client.post(
            "/api/analytics/reconciliation/repair", headers=_headers(token), json={}
        )
        assert repaired.status_code == 200
        assert repaired.json()["created_months"] == 1
        assert repaired.json()["reconciliation"]["ok"] is True

    app.dependency_overrides.clear()
    db.expire_all()
    assert db.query(Shoe).filter_by(id=shoe.id).one().mileage == 5
    month = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()
    assert (month.km, month.adjustment_km) == (5, 0)


def test_deleted_run_and_retired_shoe_can_be_undone(db, user_with_token):
    user, token = user_with_token
    other = User(username="other-user", hashed_password=get_password_hash("pass1234"))
    db.add(other)
    db.commit()
    other_token = create_access_token(data={"sub": other.username})
    with _client(db) as client:
        shoe = client.post("/api/shoes", headers=_headers(token), json={
            "brand": "A", "model": "Undo", "date": "2026-01-01",
            "monthly_km": 30,
        }).json()
        run = client.post("/api/runs", headers=_headers(token), json={
            "date": "2026-08-02", "km": 5, "shoe_id": shoe["id"],
        }).json()
        deleted = client.delete(
            f"/api/runs/{run['id']}?expected_version={run['version']}",
            headers=_headers(token),
        )
        assert deleted.status_code == 200
        delete_operation = client.get(
            "/api/operations", headers=_headers(token)
        ).json()[0]
        assert delete_operation["can_undo"] is True
        assert client.get(
            "/api/operations", headers=_headers(other_token)
        ).json() == []
        assert client.post(
            f"/api/operations/{delete_operation['id']}/undo",
            headers=_headers(other_token), json={},
        ).status_code == 404
        assert client.post(
            f"/api/operations/{delete_operation['id']}/undo",
            headers=_headers(token), json={},
        ).status_code == 200
        assert db.query(Run).filter_by(user_id=user.id).count() == 1

        current = client.get("/api/shoes/active", headers=_headers(token)).json()[0]
        retired = client.put(
            f"/api/shoes/{shoe['id']}", headers=_headers(token),
            json={
                "expected_version": current["version"],
                "is_retired": True,
                "monthly_km": 0,
            },
        )
        assert retired.status_code == 200
        retire_operation = client.get(
            "/api/operations", headers=_headers(token)
        ).json()[0]
        assert client.post(
            f"/api/operations/{retire_operation['id']}/undo",
            headers=_headers(token), json={},
        ).status_code == 200

    app.dependency_overrides.clear()
    db.expire_all()
    restored_shoe = db.query(Shoe).filter_by(id=shoe["id"]).one()
    assert restored_shoe.is_retired is False
    assert restored_shoe.monthly_km == 30
    assert analytics.mileage_reconciliation(db, user.id)["ok"] is True
