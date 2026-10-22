"""SPEC-021 credential revocation and registration across SQLite connections."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.app_factory import create_app
from backend.database import configure_sqlite_connection
from backend.services import accounts as auth
from backend.settings import settings


@pytest.fixture
def auth_app(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.sqlite'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    sessions = sessionmaker(bind=engine, autoflush=False)
    app = create_app(
        replace(settings, seed_data=False, secret_key="synthetic-auth-concurrency-key-over-32-bytes"),
        db_engine=engine,
        session_factory=sessions,
    )
    with TestClient(app) as client:
        yield app, client, sessions
    engine.dispose()


def test_overlapping_password_changes_reject_stale_snapshot_and_revoke_tokens(auth_app, monkeypatch):
    _app, client, sessions = auth_app
    username = "password-race"
    assert client.post("/api/auth/register", json={
        "username": username, "password": "initial-password",
    }).status_code == 200
    with sessions() as db:
        db.add(models.User(username="unrelated", hashed_password="synthetic", token_version=7))
        db.commit()
    both_verified = Barrier(2)
    release_second = Event()
    original_hash = auth.get_password_hash

    def controlled_hash(password):
        both_verified.wait(timeout=15)
        if password == "second-password":
            assert release_second.wait(20)
        return original_hash(password)

    def change(old_password, new_password):
        return client.post("/api/auth/change-password", json={
            "username": username, "old_password": old_password, "new_password": new_password,
        })

    monkeypatch.setattr(auth, "get_password_hash", controlled_hash)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(change, "initial-password", "first-password")
            second = pool.submit(change, "initial-password", "second-password")
            assert first.result(timeout=20).status_code == 200
            login = client.post("/api/auth/login", json={
                "username": username, "password": "first-password",
            })
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            release_second.set()
            response = second.result(timeout=20)
            assert response.status_code == 409
            assert "重新登入" in response.json()["detail"]
    finally:
        release_second.set()
        monkeypatch.setattr(auth, "get_password_hash", original_hash)

    # The rejected request cannot overwrite the first password or invalidate
    # that successful login. A later legitimate change must revoke it again.
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/login", json={
        "username": username, "password": "second-password",
    }).status_code == 401
    assert change("first-password", "third-password").status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={
        "username": username, "password": "third-password",
    }).status_code == 200
    with sessions() as db:
        assert db.query(models.User.token_version).filter(models.User.username == username).scalar() == 2
        assert db.query(models.User.token_version).filter(models.User.username == "unrelated").scalar() == 7


def _register_in_process(database_url, username, capacity, hash_gate, results):
    """A process-local Lock cannot protect these independently hosted clients."""
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    sessions = sessionmaker(bind=engine, autoflush=False)
    app = create_app(
        replace(settings, seed_data=False, max_registered_users=capacity),
        db_engine=engine,
        session_factory=sessions,
    )
    original_hash = auth.get_password_hash

    def synchronized_hash(password):
        # Old code checks capacity before this gate; new code hashes before
        # taking the database reservation, so no lock is held at the gate.
        hash_gate.wait(timeout=20)
        return original_hash(password)

    auth.get_password_hash = synchronized_hash
    client = TestClient(app, raise_server_exceptions=False)
    try:
        # The parent initialized this temporary schema; avoid competing startup
        # migrations so this test isolates request-time registration only.
        response = client.post("/api/auth/register", json={
            "username": username, "password": "synthetic-password",
        })
        results.put(response.status_code)
    finally:
        client.close()
        auth.get_password_hash = original_hash
        engine.dispose()


@pytest.mark.parametrize(
    ("usernames", "capacity", "expected"),
    [(("first", "second"), 1, [200, 403]), (("same", "same"), 2, [200, 400])],
)
def test_registration_capacity_and_duplicate_names_are_atomic_across_processes(
    auth_app, usernames, capacity, expected,
):
    import multiprocessing

    app, client, sessions = auth_app
    context = multiprocessing.get_context("spawn")
    gate, results = context.Barrier(2), context.Queue()
    workers = [context.Process(
        target=_register_in_process,
        args=(str(app.state.db_engine.url), username, capacity, gate, results),
    ) for username in usernames]
    try:
        for worker in workers:
            worker.start()
        assert sorted(results.get(timeout=30) for _ in workers) == expected
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0
        with sessions() as db:
            assert db.query(models.User).count() == 1
            assert db.query(models.User.token_version).scalar() == 0
        # A rejected transaction must release its reservation for later work.
        app.state.settings = replace(app.state.settings, max_registered_users=2)
        assert client.post("/api/auth/register", json={
            "username": "after-rejection", "password": "synthetic-password",
        }).status_code == 200
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        results.close()
