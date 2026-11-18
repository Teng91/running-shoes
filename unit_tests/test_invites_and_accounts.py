"""SPEC-075: invite-only registration, admin help, case-insensitive names and account deletion."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.credentials import get_password_hash
from backend.database import configure_sqlite_connection
from backend.dependencies import get_db
from backend.main import app
from backend.migrations import run_startup_migrations, schema_version
from backend.services import accounts
from backend.settings import Settings

PASSWORD = "pass1234"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _settings(monkeypatch, **values):
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, **values))


def _login(client, username, password=PASSWORD):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _register(client, username, invite_code=""):
    return client.post("/api/auth/register",
                       json={"username": username, "password": PASSWORD, "invite_code": invite_code})


def _admin(client, db, monkeypatch, name="Joy"):
    db.add(models.User(username=name, hashed_password=get_password_hash(PASSWORD)))
    db.commit()
    _settings(monkeypatch, admin_usernames=frozenset({name.casefold()}))
    return _login(client, name)


def test_settings_default_to_invite_only_and_fail_closed():
    assert Settings.from_env({}).registration_mode == "invite"
    assert Settings.from_env({"REGISTRATION_MODE": " OPEN "}).registration_mode == "open"
    assert Settings.from_env({"REGISTRATION_MODE": "typo"}).registration_mode == "closed"
    admins = Settings.from_env({"ADMIN_USERNAMES": "Joy, ,Xuan"})
    assert admins.is_admin("joy") and admins.is_admin("XUAN") and not admins.is_admin("other")
    assert Settings.from_env({}).agent_daily_limit_per_user == 20


def test_invite_only_registration_spends_one_use_and_rejects_every_bad_code(client, db, monkeypatch):
    headers = _admin(client, db, monkeypatch)
    _settings(monkeypatch, registration_mode="invite")
    assert client.get("/api/auth/registration").json()["mode"] == "invite"
    assert _register(client, "nocode").json()["detail"] == "Invalid invite code"

    created = client.post("/api/admin/invites", headers=headers, json={"note": "給 Xuan", "max_uses": 1, "days": 7})
    assert created.status_code == 200
    code = created.json()["code"]
    assert len(code) == 9 and code[4] == "-"
    assert "code" not in client.get("/api/admin/invites", headers=headers).json()[0], "codes are shown only once"
    assert db.query(models.Invite).one().code_hash != code

    assert _register(client, "Joy", code).json()["detail"] == "Username already registered"
    assert db.query(models.Invite).one().used_count == 0, "a failed sign-up does not spend the invite"
    assert _register(client, "Xuan", code.lower().replace("-", " ")).status_code == 200, "codes ignore case and spacing"
    assert _register(client, "third", code).json()["detail"] == "Invalid invite code", "single use"
    listed = client.get("/api/admin/invites", headers=headers).json()[0]
    assert (listed["used_count"], listed["active"], listed["note"]) == (1, False, "給 Xuan")


def test_revoked_and_expired_invites_are_rejected(client, db, monkeypatch):
    headers = _admin(client, db, monkeypatch)
    _settings(monkeypatch, registration_mode="invite")
    revoked = client.post("/api/admin/invites", headers=headers, json={"max_uses": 5}).json()
    assert client.delete(f"/api/admin/invites/{revoked['id']}", headers=headers).json()["revoked"] is True
    assert _register(client, "late", revoked["code"]).status_code == 400
    expired = client.post("/api/admin/invites", headers=headers, json={"max_uses": 5}).json()
    db.query(models.Invite).filter_by(id=expired["id"]).update(
        {"expires_at": datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)})
    db.commit()
    assert _register(client, "late", expired["code"]).status_code == 400
    assert client.delete("/api/admin/invites/999", headers=headers).status_code == 404


def test_closed_registration_and_open_mode(client, monkeypatch):
    _settings(monkeypatch, registration_mode="closed")
    assert client.get("/api/auth/registration").json()["mode"] == "closed"
    assert _register(client, "anyone").json()["detail"] == "Registration is closed"
    _settings(monkeypatch, registration_mode="open")
    assert _register(client, "anyone").status_code == 200


def test_only_admins_reach_admin_routes_and_me_says_who_is_admin(client, db, monkeypatch):
    admin = _admin(client, db, monkeypatch)
    _register(client, "member")
    member = _login(client, "member")
    for method, path in (("get", "/api/admin/invites"), ("post", "/api/admin/invites"),
                         ("delete", "/api/admin/invites/1"), ("post", "/api/admin/reset-password")):
        kwargs = {"json": {"username": "Joy"}} if path.endswith("reset-password") else {}
        if method == "post" and path.endswith("invites"):
            kwargs = {"json": {}}
        assert getattr(client, method)(path, headers=member, **kwargs).status_code == 403, path
    assert client.get("/api/admin/invites").status_code == 401
    assert client.get("/api/auth/me", headers=admin).json()["is_admin"] is True
    assert client.get("/api/auth/me", headers=member).json()["is_admin"] is False


def test_admin_reset_gives_a_temporary_password_and_ends_old_sessions(client, db, monkeypatch):
    admin = _admin(client, db, monkeypatch)
    _register(client, "Forgetful")
    old_session = _login(client, "Forgetful")
    reset = client.post("/api/admin/reset-password", headers=admin, json={"username": "forgetful"})
    assert reset.status_code == 200 and reset.json()["username"] == "Forgetful"
    temporary = reset.json()["temporary_password"]
    assert len(temporary) >= 12
    assert client.get("/api/auth/me", headers=old_session).status_code == 401
    assert client.post("/api/auth/login", json={"username": "Forgetful", "password": PASSWORD}).status_code == 401
    _login(client, "Forgetful", temporary)
    missing = client.post("/api/admin/reset-password", headers=admin, json={"username": "ghost"})
    assert missing.status_code == 404


def test_usernames_are_case_insensitive_for_sign_up_login_and_lockout(client, db):
    assert _register(client, "Runner").status_code == 200
    assert _register(client, "RUNNER").json()["detail"] == "Username already registered"
    headers = _login(client, "rUnNeR")
    assert client.get("/api/auth/me", headers=headers).json()["username"] == "Runner"
    for variant in ("runner", "RUNNER", "Runner"):
        client.post("/api/auth/login", json={"username": variant, "password": "wrong-pass"})
    bucket = db.query(models.RateLimitBucket).filter_by(scope="auth-failure-account", bucket_key="runner").one()
    assert bucket.event_count == 3, "changing case does not dodge the lockout"


def test_deleting_an_account_removes_every_row_it_owns_and_nothing_else(client, db):
    _register(client, "leaver")
    _register(client, "stayer")
    leaver, stayer = _login(client, "leaver"), _login(client, "stayer")
    for headers in (leaver, stayer):
        shoe = client.post("/api/shoes", headers=headers, json={"brand": "A", "model": "B", "date": "2026-01-01"}).json()
        assert client.post("/api/runs", headers=headers, json={"date": "2026-02-01", "km": 5, "shoe_id": shoe["id"]}).status_code == 200
        assert client.put("/api/running-goal", headers=headers, json={"start_year": 2026, "monthly_km": 100, "yearly_km": 1200}).status_code == 200
    leaver_id = db.query(models.User).filter_by(username="leaver").one().id

    wrong = client.post("/api/auth/delete-account", headers=leaver, json={"password": "wrong-pass"})
    assert wrong.status_code == 400 and wrong.json()["detail"] == "Incorrect password"
    assert client.post("/api/auth/delete-account", headers=leaver, json={"password": PASSWORD}).status_code == 200

    db.expire_all()
    assert db.query(models.User).filter_by(id=leaver_id).first() is None
    for table in accounts._account_tables():
        count = db.execute(text(f"SELECT count(*) FROM {table.name} WHERE user_id = :id"), {"id": leaver_id}).scalar()
        assert count == 0, table.name
    assert client.get("/api/auth/me", headers=leaver).status_code == 401
    assert len(client.get("/api/shoes/active", headers=stayer).json()) == 1
    assert client.post("/api/auth/login", json={"username": "leaver", "password": PASSWORD}).status_code == 401


def _name_index(engine) -> bool:
    # SQLAlchemy's inspector skips expression indexes, so ask SQLite directly.
    with engine.connect() as connection:
        return connection.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'uq_users_username_lower'"
        )).first() is not None


def _engine(tmp_path, name):
    engine = create_engine(f"sqlite:///{tmp_path / name}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    return engine, sessionmaker(bind=engine, autoflush=False)


def test_schema_eleven_adds_invites_and_a_case_insensitive_name_index_then_rolls_back(tmp_path):
    engine, sessions = _engine(tmp_path, "schema11.sqlite")
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 12
    assert "invites" in inspect(engine).get_table_names()
    assert _name_index(engine)
    script = Path("scripts/rollback_schema_eleven.sql").read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        connection.executescript(Path("scripts/rollback_schema_twelve.sql").read_text(encoding="utf-8"))
        connection.executescript(script)
        with pytest.raises(Exception, match="CHECK constraint failed"):
            connection.executescript(script)
        connection.rollback()
    finally:
        connection.close()
    assert schema_version(engine) == 10
    assert not _name_index(engine)
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 12
    engine.dispose()


def test_schema_eleven_skips_the_name_index_when_old_accounts_differ_only_by_case(tmp_path):
    engine, sessions = _engine(tmp_path, "collide.sqlite")
    run_startup_migrations(engine, sessions)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_users_username_lower"))
        connection.execute(text("UPDATE schema_metadata SET value = '10' WHERE key = 'schema_version'"))
    with sessions() as db:
        db.add_all([models.User(username="Same", hashed_password="x"), models.User(username="same", hashed_password="x")])
        db.commit()
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 12, "startup still succeeds"
    assert not _name_index(engine)
    engine.dispose()


def test_admin_can_choose_a_memorable_invite_code(client, db, monkeypatch):
    """SPEC-076: a custom code such as "Teng91" works case-insensitively and stays unique."""
    headers = _admin(client, db, monkeypatch)
    _settings(monkeypatch, registration_mode="invite")
    created = client.post("/api/admin/invites", headers=headers, json={"code": "Teng91", "max_uses": 2})
    assert created.status_code == 200 and created.json()["code"] == "TENG91"
    assert client.post("/api/admin/invites", headers=headers, json={"code": "teng91"}).json()["detail"] \
        == "Invite code already exists"
    for bad in ("ab1", "x" * 21, "跑鞋跑鞋跑鞋"):
        assert client.post("/api/admin/invites", headers=headers, json={"code": bad}).status_code == 400, bad
    assert _register(client, "friend", "teng91").status_code == 200
    assert _register(client, "friend2", " TENG91 ").status_code == 200
    assert _register(client, "friend3", "Teng91").json()["detail"] == "Invalid invite code", "two uses only"
