"""SPEC-093: fixes from the whole-project review (calendar, accounts, sessions, rounding)."""

import hashlib
import hmac
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import agent, llm, models, rate_limits, schemas
from backend.clock import DEFAULT_TIMEZONE
from backend.credentials import get_password_hash
from backend.dependencies import get_db
from backend.main import app
from backend.read_models.rounding import round_metric
from backend.services import accounts, email_codes, runs
from backend.services.errors import Invalid

PASSWORD = "pass1234"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _settings(monkeypatch, **values):
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, **values))


def _register(client, username):
    return client.post("/api/auth/register", json={"username": username, "password": PASSWORD})


def _login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_frontend_calendar_mirrors_the_backend_time_zone():
    """AC-1 (SPEC-147): until the account's zone arrives, the browser counts "today" in the same
    default zone as backend/clock.py, and never with a fixed offset."""
    state = (ROOT / "frontend" / "app-state.js").read_text(encoding="utf-8")
    assert f"const DEFAULT_ACCOUNT_TIMEZONE = '{DEFAULT_TIMEZONE}';" in state
    assert "APP_UTC_OFFSET_MINUTES" not in state
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "frontend").glob("app-*.js"))
    # Calendar days never come from the device's zone; timestamps for display may.
    assert not re.search(r"new Date\(\)\.get(FullYear|Month|Date)\(", sources)


def _runner_with_timed_run(db):
    user = models.User(username="pacer", hashed_password="synthetic")
    db.add(user)
    db.flush()
    shoe = models.Shoe(user_id=user.id, brand="A", model="B", date="2026-01-01", mileage=10, baseline_mileage=0)
    db.add(shoe)
    db.flush()
    run = models.Run(id=1, user_id=user.id, shoe_id=shoe.id, date="2026-11-01", km=10, duration_seconds=3000)
    db.add(run)
    db.commit()
    return user.id, run.id


def test_a_distance_edit_keeps_a_stored_moving_time_plausible(db):
    """AC-2: 10 km in 50 minutes cannot become 0.5 km in 50 minutes (100:00 per km)."""
    user_id, run_id = _runner_with_timed_run(db)
    with pytest.raises(Invalid, match="請一併修改或清除跑步時間"):
        runs.update_run(db, user_id, run_id, schemas.RunUpdate(km=0.5, expected_version=0))
    assert db.get(models.Run, run_id).km == 10

    runs.update_run(db, user_id, run_id, schemas.RunUpdate(km=12, expected_version=0))
    assert db.get(models.Run, run_id).km == 12
    runs.update_run(db, user_id, run_id, schemas.RunUpdate(km=0.5, duration_seconds=None, expected_version=1))
    stored = db.get(models.Run, run_id)
    assert (stored.km, stored.duration_seconds) == (0.5, None)


def test_deleting_an_account_clears_the_throttling_windows_named_by_its_id(client, db):
    """AC-3: a reused user id must not inherit the deleted account's AI and upload budgets."""
    assert _register(client, "leaver").status_code == 200
    headers = _login(client, "leaver")
    user_id = db.query(models.User).filter_by(username="leaver").one().id
    request = SimpleNamespace(app=app, headers={}, client=SimpleNamespace(host="203.0.113.9"))
    rate_limits.enforce_agent_request_limits(request, user_id)
    rate_limits.enforce_model_refresh_limits(request, user_id)
    rate_limits.enforce_restore_preview_limits(request, user_id)
    rate_limits.enforce_strava_upload_limits(request, user_id)
    rate_limits.enforce_mail_limits(request, f"user:{user_id}")
    rate_limits.enforce_mail_limits(request, f"reset:user:{user_id}")
    rate_limits.enforce_code_attempt_limit(request, email_codes.VERIFY_EMAIL, f"user:{user_id}")
    rate_limits.enforce_code_attempt_limit(request, email_codes.RESET_PASSWORD, f"user:{user_id}")
    account_keys = set(accounts.account_rate_limit_keys(user_id))
    scopes_before = {row.scope for row in db.query(models.RateLimitBucket) if row.bucket_key in account_keys}
    assert {"agent-user", "agent-user-daily", "model-refresh-user", "restore-preview-user",
            "strava-upload-user", "mail-account", "code-attempt"} <= scopes_before

    response = client.post("/api/auth/delete-account", headers=headers, json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    db.expire_all()
    remaining = {(row.scope, row.bucket_key) for row in db.query(models.RateLimitBucket)}
    assert not {key for _scope, key in remaining} & account_keys
    assert ("agent-global", "global") in remaining and ("agent-ip", "203.0.113.9") in remaining


def test_a_username_and_its_email_share_one_password_reset_mail_budget(client, db, monkeypatch):
    """AC-4: switching between the name and the bound email does not double the mails."""
    sent: list[str] = []
    monkeypatch.setattr(app.state, "mailer", lambda to, subject, body: sent.append(to))
    assert _register(client, "forgetful").status_code == 200
    db.query(models.User).filter_by(username="forgetful").update({models.User.email: "f@example.com"})
    db.commit()
    answers = [client.post("/api/auth/password-reset/request", json={"identifier": identifier}).status_code
               for identifier in ("forgetful", "F@Example.com", "FORGETFUL", "f@example.com")]
    assert answers == [200, 200, 200, 429]
    assert len(sent) == 3


def test_admin_names_cannot_be_claimed_after_the_first_account(client, db, monkeypatch):
    """AC-5: open registration hands out an unregistered admin name only to a new deployment's first account."""
    _settings(monkeypatch, registration_mode="open", admin_usernames=frozenset({"owner", "helper"}))
    assert _register(client, "Owner").status_code == 200
    taken = _register(client, "helper")
    assert taken.status_code == 400
    assert taken.json()["detail"] == accounts.USERNAME_TAKEN
    assert _register(client, "ordinary").status_code == 200
    assert db.query(models.User).filter(models.User.username.in_(["Owner", "ordinary"])).count() == 2


def test_a_non_ascii_name_logs_in_and_lockouts_share_its_identity(client, db):
    """AC-6: SQLite's lower() folds only A–Z, so lookups must not use Python's wider folding."""
    assert _register(client, "Ärger").status_code == 200
    _login(client, "Ärger")
    _login(client, "äRGER".replace("ä", "Ä"))  # ASCII letters still ignore case
    assert accounts.username_key("  ÄrGER ") == "Ärger"
    assert _register(client, "ärger").status_code == 200  # a different letter, so a different account
    assert db.query(models.User).count() == 2


def test_email_codes_use_a_key_derived_for_that_purpose_only(db):
    """AC-7: the session-signing secret is never the email-code HMAC key itself."""
    db.add(models.User(username="mailer", hashed_password=get_password_hash(PASSWORD)))
    db.commit()
    user = db.query(models.User).filter_by(username="mailer").one()
    secret = "s" * 40
    sent: list[tuple[str, str, str]] = []
    email_codes.request_email_binding(db, user, "m@example.com", send=lambda *mail: sent.append(mail),
                                      secret_key=secret)
    code = re.search(r"\b(\d{6})\b", sent[-1][1])[1]
    stored = db.query(models.EmailCode).one().code_hash
    message = f"{user.id}:{email_codes.VERIFY_EMAIL}:{code}".encode()
    assert stored != hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    assert stored == hmac.new(email_codes.code_key(secret), message, hashlib.sha256).hexdigest()
    assert email_codes.confirm_email_binding(db, user, code, secret_key=secret) == {"email": "m@example.com"}


def test_tool_calls_and_the_chat_route_release_the_database_connection(client, db, monkeypatch):
    """AC-8: a minutes-long chat stream does not keep a pooled SQLite connection checked out."""
    db.add(models.User(username="chatter", hashed_password="synthetic"))
    db.commit()
    db.query(models.User).first()
    assert db.in_transaction()
    monkeypatch.setattr(agent, "_execute_tool", lambda *_args: str(db.query(models.User).count()))
    assert agent._execute_tool_safely("shoe_summary", {}, db, 1) == "1"
    assert not db.in_transaction()

    assert _register(client, "streamer").status_code == 200
    headers = _login(client, "streamer")
    observed: list[bool] = []

    def fake_stream(**kwargs):
        observed.append(kwargs["db"].in_transaction())
        yield 'data: {"type":"done"}\n\n'

    monkeypatch.setattr(llm, "resolve_allowed_model", lambda provider, model: "vendor/model:free")
    monkeypatch.setattr("backend.routers.agent.agent_service.run_agent_stream", fake_stream)
    response = client.post("/api/agent/chat/stream", headers=headers,
                           json={"user_message": "hi", "provider": "openrouter", "history": []})
    assert response.status_code == 200, response.text
    assert observed == [False]


def test_aggregates_round_halves_up_like_entered_values():
    """AC-9: one rounding rule from input to every read model."""
    assert round_metric(2.675) == 2.68 and round(2.675, 2) == 2.67
    assert round_metric(0.125) == 0.13 and round_metric(-1.005) == -1.01
    assert round_metric(None) == 0.0 and round_metric(12.3456, 1) == 12.3
    bare = re.compile(r"(?<![\w.])round\([^()]*(?:\([^()]*\)[^()]*)*,\s*\d+\s*\)")
    for path in (ROOT / "backend" / "read_models").glob("*.py"):
        if path.name != "rounding.py":
            assert not bare.search(path.read_text(encoding="utf-8")), path.name
