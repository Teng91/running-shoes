"""SPEC-019: committed receipts, annual aggregation and additive migrations."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.app_factory import create_app
from backend.auth import create_access_token
from backend.database import Base, configure_sqlite_connection, get_db
from backend.main import app
from backend.migrations import run_startup_migrations, schema_version
from backend.read_models.runs import year_run_summary
from backend.settings import settings


@pytest.fixture
def request_client(db, user_with_token):
    def session():
        yield db

    app.dependency_overrides[get_db] = session
    user, token = user_with_token
    shoe = models.Shoe(user_id=user.id, brand="Test", model="Receipt", date="2026-01-01")
    db.add(shoe)
    db.commit()
    payload = {"shoe_id": shoe.id, "date": "2026-01-05", "km": 5}
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "test-operation-key-0001"}
    try:
        with TestClient(app) as client:
            yield client, headers, payload
    finally:
        app.dependency_overrides.clear()


def test_replayed_run_returns_original_snapshot_and_updates_mileage_once(db, request_client):
    client, headers, payload = request_client
    first = client.post("/api/runs", json=payload, headers=headers)
    assert first.status_code == 200
    assert client.post("/api/runs", json=payload, headers=headers).json() == first.json()
    assert db.query(models.Run).count() == 1
    assert db.query(models.RunCreationRequest).count() == 1
    assert db.get(models.Shoe, payload["shoe_id"]).mileage == 5
    assert db.query(models.MonthlyMileage).one().km == 5
    changed = client.post("/api/runs", json={**payload, "km": 10}, headers=headers)
    assert changed.status_code == 409
    assert db.query(models.Run).count() == 1


def test_deleted_run_is_not_recreated_by_replayed_request(db, request_client):
    client, headers, payload = request_client
    original = client.post("/api/runs", json=payload, headers=headers).json()
    assert client.delete(f"/api/runs/{original['id']}", headers=headers).status_code == 200
    assert client.post("/api/runs", json=payload, headers=headers).json() == original
    assert db.query(models.Run).count() == 0
    assert db.get(models.Shoe, payload["shoe_id"]).mileage == 0


def test_request_keys_are_user_scoped_and_legacy_clients_remain_supported(db, request_client):
    client, headers, payload = request_client
    assert client.post("/api/runs", json=payload, headers=headers).status_code == 200
    other = models.User(username="receipt-other", hashed_password="synthetic")
    db.add(other)
    db.flush()
    shoe = models.Shoe(user_id=other.id, brand="Other", model="Private", date="2026-01-01")
    db.add(shoe)
    db.commit()
    other_headers = {**headers, "Authorization": f"Bearer {create_access_token({'sub': other.username})}"}
    assert client.post("/api/runs", json=payload, headers=other_headers).status_code == 404
    assert db.query(models.RunCreationRequest).count() == 1
    assert client.post("/api/runs", json={**payload, "shoe_id": shoe.id}, headers=other_headers).status_code == 200
    legacy = {"Authorization": headers["Authorization"]}
    assert client.post("/api/runs", json=payload, headers=legacy).status_code == 200
    assert db.query(models.Run).count() == 3


@pytest.mark.parametrize("key", ["short", "!" * 20, "x" * 129])
def test_invalid_operation_keys_never_create_receipts_or_runs(db, request_client, key):
    client, headers, payload = request_client
    response = client.post("/api/runs", json=payload, headers={**headers, "Idempotency-Key": key})
    assert response.status_code == 422
    assert db.query(models.Run).count() == db.query(models.RunCreationRequest).count() == 0


def test_failed_run_transaction_does_not_poison_its_request_key(db, request_client, monkeypatch):
    from backend.routers import runs

    client, headers, payload = request_client
    original = runs.runs_service.apply_run_mileage_deltas

    def fail(*args):
        raise RuntimeError("synthetic transaction failure")

    monkeypatch.setattr(runs.runs_service, "apply_run_mileage_deltas", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        client.post("/api/runs", json=payload, headers=headers)
    assert db.query(models.RunCreationRequest).count() == 0
    assert db.query(models.Run).count() == 0
    monkeypatch.setattr(runs.runs_service, "apply_run_mileage_deltas", original)
    assert client.post("/api/runs", json=payload, headers=headers).status_code == 200


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_requests_share_one_committed_receipt(tmp_path, conflicting):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.sqlite'}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    sessions = sessionmaker(bind=engine, autoflush=False)
    config = replace(settings, seed_data=False)
    application = create_app(config, db_engine=engine, session_factory=sessions)
    with TestClient(application) as client:
        with sessions() as db:
            user = models.User(username="parallel", hashed_password="synthetic")
            db.add(user)
            db.flush()
            shoe = models.Shoe(user_id=user.id, brand="A", model="B", date="2026-01-01")
            db.add(shoe)
            db.commit()
            shoe_id = shoe.id
        headers = {"Authorization": f"Bearer {create_access_token({'sub': 'parallel'})}", "Idempotency-Key": "concurrent-operation-0001"}

        def submit(index):
            return client.post("/api/runs", json={"shoe_id": shoe_id, "date": "2026-01-05", "km": 5 + index * conflicting}, headers=headers)

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(submit, range(4)))
        successes = [response for response in responses if response.status_code == 200]
        assert len(successes) == (1 if conflicting else 4)
        assert all(response.status_code in (200, 409) for response in responses)
        assert all(response.json() == successes[0].json() for response in successes)
        with sessions() as db:
            assert db.query(models.Run).count() == 1
            assert db.query(models.RunCreationRequest).count() == 1
            assert db.get(models.Shoe, shoe_id).mileage == successes[0].json()["km"]
    engine.dispose()


def test_receipt_replay_succeeds_even_after_quota_reached(db, request_client, monkeypatch):

    client, headers, payload = request_client
    original = client.post("/api/runs", json=payload, headers=headers).json()
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, max_runs_per_user=1))
    assert client.post("/api/runs", json=payload, headers=headers).json() == original
    assert client.post("/api/runs", json=payload, headers={**headers, "Idempotency-Key": "a-new-operation-0001"}).status_code == 409
    assert db.query(models.RunCreationRequest).count() == 1


def test_year_summary_preserves_deleted_shoe_history_and_scopes_users(db, request_client):
    client, headers, payload = request_client
    shoe = db.get(models.Shoe, payload["shoe_id"])
    other = models.User(username="annual-private", hashed_password="synthetic")
    db.add(other)
    db.flush()
    hidden = models.Shoe(user_id=other.id, brand="Private", model="Private", date="2026-01-01")
    db.add(hidden)
    db.flush()
    shoe.is_deleted = True
    db.add_all([
        models.Run(user_id=shoe.user_id, shoe_id=shoe.id, date="2026-01-05", km=5),
        models.Run(user_id=shoe.user_id, shoe_id=shoe.id, date="2026-12-31", km=10),
        models.Run(user_id=shoe.user_id, shoe_id=shoe.id, date="2025-12-31", km=100),
        models.Run(user_id=other.id, shoe_id=hidden.id, date="2026-01-05", km=999),
    ])
    db.commit()
    response = client.get("/api/runs/year-summary?year=2026", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_km"] == 15
    assert body["run_count"] == 2
    assert body["monthly_km"] == [5] + [0] * 10 + [10]
    assert body["shoes"] == [{"shoe_id": shoe.id, "monthly_km": body["monthly_km"]}]
    assert client.get("/api/runs/year-summary?year=2101", headers=headers).status_code == 422
    assert client.get("/api/runs/year-summary?year=2024", headers=headers).json()["shoes"] == []


def test_year_summary_uses_one_grouped_query(db, user_with_token):
    statements = []
    user_id = user_with_token[0].id
    engine = db.get_bind()

    def record(*args):
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert year_run_summary(db, user_id, 2026)["total_km"] == 0
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) == 1
    assert "GROUP BY" in statements[0]


def test_schema_two_adds_receipts_without_changing_business_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name != "run_creation_requests"])
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(models.User(username="preserved", hashed_password="synthetic"))
        db.commit()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE schema_metadata (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)"))
        connection.execute(text("INSERT INTO schema_metadata VALUES ('schema_version', '1')"))
    for _ in range(2):
        run_startup_migrations(engine, sessions)
        assert schema_version(engine) == 4
    assert "run_creation_requests" in inspect(engine).get_table_names()
    with sessions() as db:
        assert db.query(models.User).one().username == "preserved"
        assert db.query(models.RunCreationRequest).count() == 0
    engine.dispose()
