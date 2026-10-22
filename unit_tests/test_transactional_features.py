"""SPEC-020 app-local settings, atomic quotas and application service transactions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.app_factory import create_app
from backend.auth import create_access_token
from backend.database import configure_sqlite_connection
from backend.settings import settings


@pytest.fixture
def feature_app(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'features.sqlite'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    sessions = sessionmaker(bind=engine, autoflush=False)
    config = replace(settings, seed_data=False, max_shoes_per_user=1, max_runs_per_user=1)
    app = create_app(config, db_engine=engine, session_factory=sessions)
    with TestClient(app) as client:
        with sessions() as db:
            user = models.User(username="features", hashed_password="synthetic")
            db.add(user)
            db.commit()
        headers = {"Authorization": f"Bearer {create_access_token({'sub': 'features'})}"}
        yield app, client, sessions, headers
    engine.dispose()


def shoe_payload():
    return {"brand": "Synthetic", "model": "Quota", "date": "2026-01-01"}


def test_factory_quotas_apply_to_each_app_without_global_patching(feature_app):
    app, client, sessions, headers = feature_app
    first = client.post("/api/shoes", json=shoe_payload(), headers=headers)
    assert first.status_code == 200
    assert client.post("/api/shoes", json=shoe_payload(), headers=headers).status_code == 409
    payload = {"date": "2026-01-02", "km": 5, "shoe_id": first.json()["id"]}
    assert client.post("/api/runs", json=payload, headers=headers).status_code == 200
    assert client.post("/api/runs", json=payload, headers=headers).status_code == 409
    other = create_app(
        replace(app.state.settings, max_shoes_per_user=2, max_runs_per_user=2),
        db_engine=app.state.db_engine,
        session_factory=sessions,
    )
    with TestClient(other) as second:
        assert second.post("/api/shoes", json=shoe_payload(), headers=headers).status_code == 200
        assert second.post("/api/runs", json=payload, headers=headers).status_code == 200
    assert client.post("/api/shoes", json=shoe_payload(), headers=headers).status_code == 409
    assert client.post("/api/runs", json=payload, headers=headers).status_code == 409


def test_concurrent_shoe_creates_cannot_exceed_quota(feature_app):
    _app, client, sessions, headers = feature_app
    start = Barrier(4)

    def submit(_):
        start.wait(timeout=10)
        return client.post("/api/shoes", json=shoe_payload(), headers=headers).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert sorted(results) == [200, 409, 409, 409]
    with sessions() as db:
        assert db.query(models.Shoe).count() == 1


def test_registration_uses_factory_capacity(feature_app):
    app, client, _sessions, _headers = feature_app
    app.state.settings = replace(app.state.settings, max_registered_users=1)
    result = client.post(
        "/api/auth/register", json={"username": "extra", "password": "synthetic-pass"}
    )
    assert result.status_code == 403


def _process_shoe_create(database_url, user_id, start, results):
    """Independent process/session: a process-local lock cannot make this pass."""
    import time

    from backend.schemas import ShoeCreate
    from backend.services.errors import Conflict
    from backend.services.shoes import create_shoe

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))

    def pause_after_count(_connection, _cursor, statement, *_args):
        if "count(" in statement and "shoes" in statement:
            time.sleep(0.1)

    event.listen(engine, "after_cursor_execute", pause_after_count)
    results.put("ready")
    try:
        assert start.wait(10)
        with sessionmaker(bind=engine, autoflush=False)() as db:
            try:
                create_shoe(db, user_id, ShoeCreate(**shoe_payload()), max_shoes=1)
            except Conflict:
                results.put(409)
            else:
                results.put(200)
    finally:
        engine.dispose()


def test_shoe_quota_is_enforced_across_processes(feature_app):
    import multiprocessing

    app, _client, sessions, _headers = feature_app
    with sessions() as db:
        user_id = db.query(models.User.id).scalar()
    context = multiprocessing.get_context("spawn")
    start, results = context.Event(), context.Queue()
    workers = [
        context.Process(
            target=_process_shoe_create,
            args=(
                str(app.state.db_engine.url),
                user_id,
                start,
                results,
            ),
        )
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        assert [results.get(timeout=15) for _ in workers] == ["ready", "ready"]
        start.set()
        assert sorted(results.get(timeout=15) for _ in workers) == [200, 409]
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0
        with sessions() as db:
            assert db.query(models.Shoe).count() == 1
            assert db.query(models.User.token_version).scalar() == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        results.close()


def test_run_quota_serializes_distinct_and_legacy_creations(feature_app):
    _app, client, sessions, headers = feature_app
    shoe = client.post("/api/shoes", json=shoe_payload(), headers=headers).json()
    payload = {"date": "2026-01-02", "km": 5, "shoe_id": shoe["id"]}
    start = Barrier(4)

    def submit(index):
        start.wait(timeout=10)
        request_headers = {
            **headers,
            **({"Idempotency-Key": f"synthetic-operation-{index}"} if index % 2 else {}),
        }
        return client.post("/api/runs", json=payload, headers=request_headers).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(submit, range(4))) == [200, 409, 409, 409]
    with sessions() as db:
        assert db.query(models.Run).count() == 1
        assert db.query(models.Shoe.mileage).scalar() == 5
        assert db.query(models.MonthlyMileage.km).scalar() == 5


def test_factory_upload_limit_does_not_leak_to_another_app(feature_app):
    app, _client, sessions, headers = feature_app
    small = create_app(
        replace(app.state.settings, max_strava_csv_bytes=10),
        db_engine=app.state.db_engine,
        session_factory=sessions,
    )
    with TestClient(small) as client:
        assert (
            client.post(
                "/api/runs/import/strava/preview",
                headers=headers,
                files={"file": ("test.csv", b"x" * 11, "text/csv")},
            ).status_code
            == 413
        )
        assert (
            client.post(
                "/api/runs/import/strava/preview",
                headers={**headers, "Content-Length": str(2 * 1024 * 1024)},
                content=b"",
            ).status_code
            == 413
        )
    with TestClient(app) as client:
        # Same file reaches parser in the app with the ordinary upload budget.
        assert (
            client.post(
                "/api/runs/import/strava/preview",
                headers=headers,
                files={"file": ("test.csv", b"x" * 11, "text/csv")},
            ).status_code
            == 400
        )


def test_factory_strava_quota_uses_same_limit_as_manual_runs(feature_app):
    _app, client, sessions, headers = feature_app
    shoe = client.post("/api/shoes", json=shoe_payload(), headers=headers).json()
    payload = {"date": "2026-01-02", "km": 5, "shoe_id": shoe["id"]}
    assert client.post("/api/runs", json=payload, headers=headers).status_code == 200
    csv = "活動 ID,活動日期,活動類型,活動裝備,距離\n9001,2026年1月3日,跑步,Quota,1000\n"
    response = client.post(
        "/api/runs/import/strava",
        headers=headers,
        data={"mapping": '{"Quota": ' + str(shoe["id"]) + "}"},
        files={"file": ("test.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 409
    with sessions() as db:
        assert db.query(models.Run).count() == 1
        assert db.query(models.StravaImport).count() == 0
        assert db.query(models.Shoe.mileage).scalar() == 5
