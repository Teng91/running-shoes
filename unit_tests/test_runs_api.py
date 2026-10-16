import pytest
from fastapi.testclient import TestClient

from backend.auth import get_password_hash
from backend.database import get_db
from backend.main import app
from backend.models import MonthlyMileage, Shoe, User


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ── Run Log CRUD Tests ─────────────────────────────────

def test_run_log_crud(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    headers = _auth_header(token)

    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 8.25, "shoe_id": shoe.id,
    })
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert created.json()["version"] == 0
    db.refresh(shoe)
    assert shoe.mileage == 8.25
    august = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()
    assert august.km == 8.25

    listed = client.get("/api/runs", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["km"] == 8.25

    updated = client.put(f"/api/runs/{run_id}", headers=headers, json={
        "date": "2026-09-01", "km": 10.5,
    })
    assert updated.status_code == 200
    assert updated.json()["km"] == 10.5
    assert updated.json()["version"] == 1
    db.refresh(shoe)
    db.refresh(august)
    september = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=9
    ).one()
    assert shoe.mileage == 10.5
    assert august.km == 0
    assert september.km == 10.5
    omitted = client.put(f"/api/runs/{run_id}", headers=headers, json={})
    assert omitted.status_code == 200
    assert omitted.json()["km"] == 10.5

    deleted = client.delete(f"/api/runs/{run_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/runs", headers=headers).json() == []
    db.refresh(shoe)
    db.refresh(september)
    assert shoe.mileage == 0
    assert september.km == 0


def test_multiple_runs_atomically_share_one_monthly_aggregate(
    client, db, user_with_token
):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)

    first = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 5, "shoe_id": shoe.id,
    })
    second = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-20", "km": 7, "shoe_id": shoe.id,
    })

    assert first.status_code == 200
    assert second.status_code == 200
    db.expire_all()
    aggregates = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).all()
    assert len(aggregates) == 1
    assert aggregates[0].km == 12
    assert aggregates[0].version == 1


def test_run_update_rejects_stale_version_without_double_applying_mileage(
    client, db, user_with_token
):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 8, "shoe_id": shoe.id,
    }).json()

    first = client.put(f"/api/runs/{created['id']}", headers=headers, json={
        "km": 10, "expected_version": created["version"],
    })
    stale = client.put(f"/api/runs/{created['id']}", headers=headers, json={
        "km": 12, "expected_version": created["version"],
    })

    assert first.status_code == 200
    assert first.json()["version"] == 1
    assert stale.status_code == 409
    assert "重新載入" in stale.json()["detail"]
    stale_delete = client.delete(
        f"/api/runs/{created['id']}?expected_version={created['version']}",
        headers=headers,
    )
    assert stale_delete.status_code == 409
    db.expire_all()
    assert db.get(Shoe, shoe.id).mileage == 10
    monthly = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()
    assert monthly.km == 10


def test_delete_shoe_with_run_log_preserves_history(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    headers = _auth_header(token)
    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 8.25, "shoe_id": shoe.id,
    })
    assert created.status_code == 200

    deleted = client.delete(f"/api/shoes/{shoe.id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/shoes/active", headers=headers).json() == []
    assert client.get("/api/runs", headers=headers).json()[0]["shoe_id"] == shoe.id
    db.refresh(shoe)
    assert shoe.is_deleted is True

    # A deleted shoe cannot be edited, selected for a new run, or deleted again.
    assert client.put(
        f"/api/shoes/{shoe.id}", headers=headers, json={"brand": "Hidden"}
    ).status_code == 404
    assert client.post("/api/runs", headers=headers, json={
        "date": "2026-08-13", "km": 5, "shoe_id": shoe.id,
    }).status_code == 404
    assert client.delete(f"/api/shoes/{shoe.id}", headers=headers).status_code == 404


def test_run_update_applies_net_delta_when_totals_were_manually_lowered(
    client, db, user_with_token
):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)

    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 8, "shoe_id": shoe.id,
    })
    assert created.status_code == 200
    monthly = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()

    # Manual totals remain supported, so editing a run must apply only its net change.
    shoe.mileage = 3
    monthly.km = 2
    db.commit()
    updated = client.put(
        f"/api/runs/{created.json()['id']}", headers=headers, json={"km": 10}
    )

    assert updated.status_code == 200
    db.refresh(shoe)
    db.refresh(monthly)
    assert shoe.mileage == 5
    assert monthly.km == 4


def test_run_log_orders_newest_first_and_can_change_owned_shoe(client, db, user_with_token):
    user, token = user_with_token
    first_shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    second_shoe = Shoe(user_id=user.id, brand="Asics", model="Novablast", date="2026-02-01")
    db.add_all([first_shoe, second_shoe])
    db.commit()
    headers = _auth_header(token)
    older = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-01", "km": 5, "shoe_id": first_shoe.id,
    }).json()
    newer = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-15", "km": 8, "shoe_id": first_shoe.id,
    }).json()

    listed = client.get("/api/runs", headers=headers).json()
    assert [run["id"] for run in listed] == [newer["id"], older["id"]]
    changed = client.put(f"/api/runs/{older['id']}", headers=headers, json={
        "shoe_id": second_shoe.id,
    })
    assert changed.status_code == 200
    assert changed.json()["shoe_id"] == second_shoe.id
    db.refresh(first_shoe)
    db.refresh(second_shoe)
    monthly = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()
    assert first_shoe.mileage == 8
    assert second_shoe.mileage == 5
    assert monthly.km == 13


def test_run_log_supports_month_filters_and_pagination(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    for run_date, km in (
        ("2025-12-31", 3),
        ("2026-08-01", 5),
        ("2026-08-15", 8),
        ("2026-09-01", 10),
    ):
        assert client.post("/api/runs", headers=headers, json={
            "date": run_date, "km": km, "shoe_id": shoe.id,
        }).status_code == 200

    august = client.get(
        "/api/runs?year=2026&month=8&limit=1&offset=0", headers=headers
    )
    august_second_page = client.get(
        "/api/runs?year=2026&month=8&limit=1&offset=1", headers=headers
    )
    year = client.get("/api/runs?year=2026", headers=headers)
    invalid = client.get("/api/runs?month=8", headers=headers)

    assert august.status_code == 200
    assert [row["date"] for row in august.json()] == ["2026-08-15"]
    assert [row["date"] for row in august_second_page.json()] == ["2026-08-01"]
    assert [row["date"] for row in year.json()] == [
        "2026-09-01", "2026-08-15", "2026-08-01",
    ]
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "month requires year"


def test_run_log_limit(client, db, user_with_token, monkeypatch):

    monkeypatch.setattr("backend.routers.runs.MAX_RUNS_PER_USER", 1)
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    payload = {"date": "2026-08-01", "km": 5, "shoe_id": shoe.id}
    assert client.post("/api/runs", headers=headers, json=payload).status_code == 200
    limited = client.post("/api/runs", headers=headers, json=payload)
    assert limited.status_code == 409
    assert limited.json()["detail"] == "跑步紀錄已達上限"


@pytest.mark.parametrize("payload", [
    {"date": "2026-02-30", "km": 5, "shoe_id": 1},
    {"date": "2026-08-12", "km": 0, "shoe_id": 1},
    {"date": "2026-08-12", "km": 1001, "shoe_id": 1},
])
def test_run_log_rejects_invalid_payload(client, user_with_token, payload):
    _, token = user_with_token
    assert client.post("/api/runs", headers=_auth_header(token), json=payload).status_code == 422


@pytest.mark.parametrize("payload", [
    {"date": None},
    {"km": None},
    {"shoe_id": None},
])
def test_run_log_update_rejects_explicit_nulls(client, db, user_with_token, payload):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 5, "shoe_id": shoe.id,
    })
    run_id = created.json()["id"]

    rejected = client.put(f"/api/runs/{run_id}", headers=headers, json=payload)
    assert rejected.status_code == 422
    unchanged = client.get("/api/runs", headers=headers).json()[0]
    assert unchanged["date"] == "2026-08-12"
    assert unchanged["km"] == 5
    assert unchanged["shoe_id"] == shoe.id


def test_run_log_rejects_another_users_shoe_and_record(client, db):
    from backend.auth import create_access_token

    alice = User(username="run-alice", hashed_password=get_password_hash("pass1234"))
    bob = User(username="run-bob", hashed_password=get_password_hash("pass1234"))
    db.add_all([alice, bob])
    db.commit()
    shoe = Shoe(user_id=alice.id, brand="Asics", model="Novablast", date="2026-01-01")
    bob_shoe = Shoe(user_id=bob.id, brand="Nike", model="Pegasus", date="2026-01-02")
    db.add_all([shoe, bob_shoe])
    db.commit()
    alice_headers = _auth_header(create_access_token(data={"sub": alice.username}))
    bob_headers = _auth_header(create_access_token(data={"sub": bob.username}))

    forbidden_create = client.post("/api/runs", headers=bob_headers, json={
        "date": "2026-08-12", "km": 5, "shoe_id": shoe.id,
    })
    assert forbidden_create.status_code == 404

    created = client.post("/api/runs", headers=alice_headers, json={
        "date": "2026-08-12", "km": 5, "shoe_id": shoe.id,
    })
    run_id = created.json()["id"]
    forbidden_reassign = client.put(f"/api/runs/{run_id}", headers=alice_headers, json={
        "shoe_id": bob_shoe.id,
    })
    assert forbidden_reassign.status_code == 404
    assert client.get("/api/runs", headers=bob_headers).json() == []
    assert client.put(f"/api/runs/{run_id}", headers=bob_headers, json={"km": 7}).status_code == 404
    assert client.delete(f"/api/runs/{run_id}", headers=bob_headers).status_code == 404
