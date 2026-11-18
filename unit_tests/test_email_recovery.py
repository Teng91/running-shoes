"""SPEC-079: email binding and password reset with one-time codes; no real mail is ever sent."""

import re
import smtplib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.credentials import get_password_hash
from backend.database import configure_sqlite_connection
from backend.dependencies import get_db
from backend.mailer import MailError, smtp_mailer
from backend.main import app
from backend.migrations import run_startup_migrations, schema_version
from backend.settings import Settings

PASSWORD = "pass1234"


class Outbox:
    def __init__(self):
        self.messages: list[tuple[str, str, str]] = []
        self.fail = False

    def __call__(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise MailError("寄信失敗，請稍後再試")
        self.messages.append((to, subject, body))

    def code(self) -> str:
        return re.search(r"\b(\d{6})\b", self.messages[-1][1])[1]


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(app.state, "mailer", box)
    return box


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _account(client, name):
    assert client.post("/api/auth/register", json={"username": name, "password": PASSWORD}).status_code == 200
    token = client.post("/api/auth/login", json={"username": name, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _bind(client, outbox, headers, email):
    assert client.post("/api/auth/email/request", headers=headers, json={"email": email}).status_code == 200
    return client.post("/api/auth/email/confirm", headers=headers, json={"code": outbox.code()})


def test_settings_enable_mail_only_with_both_credentials():
    assert not Settings.from_env({}).mail_enabled
    assert not Settings.from_env({"SMTP_USERNAME": "a@gmail.com"}).mail_enabled
    config = Settings.from_env({"SMTP_USERNAME": " a@gmail.com ", "SMTP_PASSWORD": "abcd efgh ijkl mnop"})
    assert config.mail_enabled and config.smtp_password == "abcdefghijklmnop" and config.smtp_username == "a@gmail.com"
    assert smtp_mailer(Settings.from_env({})) is None


def test_smtp_sender_uses_starttls_login_and_hides_failures(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent.append(("starttls",))

        def login(self, user, password):
            sent.append(("login", user, password))

        def send_message(self, message):
            sent.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    send = smtp_mailer(Settings.from_env({"SMTP_USERNAME": "bot@gmail.com", "SMTP_PASSWORD": "secret"}))
    send("me@example.com", "跑鞋追蹤驗證碼：123456", "body")
    assert sent == [("connect", "smtp.gmail.com", 587), ("starttls",), ("login", "bot@gmail.com", "secret"),
                    ("send", "me@example.com", "跑鞋追蹤驗證碼：123456")]

    def broken(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials secret")
    monkeypatch.setattr(smtplib, "SMTP", broken)
    with pytest.raises(MailError) as error:
        send("me@example.com", "s", "b")
    assert "secret" not in str(error.value)


def test_email_is_bound_only_after_the_emailed_code_is_confirmed(client, db, outbox):
    headers = _account(client, "Binder")
    assert client.get("/api/auth/registration").json()["mail_enabled"] is True
    assert client.post("/api/auth/email/request", headers=headers, json={"email": "not-an-email"}).status_code == 400
    assert client.post("/api/auth/email/request", headers=headers, json={"email": " Me@Example.COM "}).status_code == 200
    to, _subject, body = outbox.messages[-1]
    assert to == "me@example.com" and "綁定 email" in body
    assert client.get("/api/auth/me", headers=headers).json()["email"] is None, "not bound before the code"
    code_row = db.query(models.EmailCode).one()
    assert outbox.code() not in code_row.code_hash, "only an HMAC is stored"
    wrong = client.post("/api/auth/email/confirm", headers=headers, json={"code": "000000" if outbox.code() != "000000" else "111111"})
    assert wrong.json()["detail"] == "Incorrect or expired code"
    assert client.post("/api/auth/email/confirm", headers=headers, json={"code": outbox.code()}).json() == {"email": "me@example.com"}
    assert client.get("/api/auth/me", headers=headers).json()["email"] == "me@example.com"
    assert db.query(models.EmailCode).count() == 0

    other = _account(client, "Other")
    taken = client.post("/api/auth/email/request", headers=other, json={"email": "ME@example.com"})
    assert taken.status_code == 409 and taken.json()["detail"] == "Email already in use"
    assert client.post("/api/auth/email/remove", headers=headers).json() == {"email": None}
    assert client.get("/api/auth/me", headers=headers).json()["email"] is None


def test_codes_expire_and_lock_after_five_wrong_attempts(client, db, outbox):
    headers = _account(client, "Locker")
    client.post("/api/auth/email/request", headers=headers, json={"email": "lock@example.com"})
    code = outbox.code()
    wrong = "123456" if code != "123456" else "654321"
    for _ in range(5):
        client.post("/api/auth/email/confirm", headers=headers, json={"code": wrong})
    assert client.post("/api/auth/email/confirm", headers=headers, json={"code": code}).status_code == 400, "locked"

    client.post("/api/auth/email/request", headers=headers, json={"email": "lock@example.com"})
    db.query(models.EmailCode).update({"expires_at": datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)})
    db.commit()
    assert client.post("/api/auth/email/confirm", headers=headers, json={"code": outbox.code()}).status_code == 400


def test_password_reset_by_username_or_email_ends_old_sessions(client, outbox):
    headers = _account(client, "Forgetful")
    assert _bind(client, outbox, headers, "forget@example.com").status_code == 200
    for identifier in ("forgetful", "FORGET@example.com"):
        assert client.post("/api/auth/password-reset/request", json={"identifier": identifier}).json() == {"ok": True}
        assert outbox.messages[-1][0] == "forget@example.com" and "重設密碼" in outbox.messages[-1][2]
    code = outbox.code()
    short = client.post("/api/auth/password-reset/confirm",
                        json={"identifier": "Forgetful", "code": code, "new_password": "short"})
    assert short.status_code == 400
    done = client.post("/api/auth/password-reset/confirm",
                       json={"identifier": "Forgetful", "code": code, "new_password": "brand-new-pass"})
    assert done.json() == {"ok": True}
    assert client.get("/api/auth/me", headers=headers).status_code == 401, "old sessions end"
    assert client.post("/api/auth/login", json={"username": "Forgetful", "password": "brand-new-pass"}).status_code == 200
    again = client.post("/api/auth/password-reset/confirm",
                        json={"identifier": "Forgetful", "code": code, "new_password": "another-pass"})
    assert again.status_code == 400, "a code works once"


def test_reset_requests_never_reveal_whether_an_account_or_email_exists(client, outbox):
    _account(client, "NoEmail")
    answers = [client.post("/api/auth/password-reset/request", json={"identifier": name}).json()
               for name in ("ghost", "NoEmail", "nobody@example.com")]
    assert answers == [{"ok": True}] * 3
    assert outbox.messages == []
    bad = client.post("/api/auth/password-reset/confirm",
                      json={"identifier": "ghost", "code": "123456", "new_password": "whatever-pass"})
    assert bad.json()["detail"] == "Incorrect or expired code"


def test_reset_mail_failure_keeps_the_same_answer(client, outbox):
    headers = _account(client, "Unlucky")
    _bind(client, outbox, headers, "unlucky@example.com")
    outbox.fail = True
    assert client.post("/api/auth/password-reset/request", json={"identifier": "Unlucky"}).json() == {"ok": True}
    failed = client.post("/api/auth/email/request", headers=headers, json={"email": "new@example.com"})
    assert failed.status_code == 503 and failed.json()["detail"] == "寄信失敗，請稍後再試"


def test_mail_routes_are_off_without_smtp_and_rate_limited(client, db, monkeypatch, outbox):
    headers = _account(client, "Limited")
    for _ in range(3):
        assert client.post("/api/auth/email/request", headers=headers, json={"email": "l@example.com"}).status_code == 200
    limited = client.post("/api/auth/email/request", headers=headers, json={"email": "l@example.com"})
    assert limited.status_code == 429, "three codes per account every 10 minutes"
    monkeypatch.setattr(app.state, "mailer", None)
    assert client.get("/api/auth/registration").json()["mail_enabled"] is False
    off = client.post("/api/auth/password-reset/request", json={"identifier": "Limited"})
    assert off.status_code == 503


def test_deleting_an_account_removes_its_email_codes(client, db, outbox):
    headers = _account(client, "Leaving")
    client.post("/api/auth/email/request", headers=headers, json={"email": "leave@example.com"})
    assert client.post("/api/auth/delete-account", headers=headers, json={"password": PASSWORD}).status_code == 200
    db.expire_all()
    assert db.query(models.EmailCode).count() == 0


def _engine(tmp_path, name):
    engine = create_engine(f"sqlite:///{tmp_path / name}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    return engine, sessionmaker(bind=engine, autoflush=False)


def test_schema_twelve_adds_email_and_codes_then_rolls_back(tmp_path):
    engine, sessions = _engine(tmp_path, "schema12.sqlite")
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 12
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1 FROM sqlite_master WHERE name = 'uq_users_email_lower'")).first()
        assert connection.execute(text("SELECT 1 FROM sqlite_master WHERE name = 'email_codes'")).first()
    script = Path("scripts/rollback_schema_twelve.sql").read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        connection.executescript(script)
        with pytest.raises(Exception, match="CHECK constraint failed"):
            connection.executescript(script)
        connection.rollback()
    finally:
        connection.close()
    assert schema_version(engine) == 11
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 12
    engine.dispose()


def test_settings_replace_keeps_mail_flag_consistent():
    config = replace(Settings.from_env({}), smtp_username="x@gmail.com", smtp_password="y")
    assert config.mail_enabled


def _notices(outbox):
    return [message for message in outbox.messages if message[1] == "跑鞋追蹤：你的密碼已變更"]


def test_every_password_change_notifies_the_bound_email(client, db, outbox, monkeypatch):
    """SPEC-083: changing, resetting by email or by the admin all send a notice to the bound address."""
    headers = _account(client, "Noticed")
    _bind(client, outbox, headers, "noticed@example.com")

    assert client.post("/api/auth/change-password", json={
        "username": "noticed", "old_password": PASSWORD, "new_password": "second-pass"}).status_code == 200
    to, _subject, body = _notices(outbox)[-1]
    assert to == "noticed@example.com" and "「Noticed」" in body and "輸入目前密碼後更改" in body
    assert "忘記密碼？" in body and "台灣時間" in body

    client.post("/api/auth/password-reset/request", json={"identifier": "Noticed"})
    client.post("/api/auth/password-reset/confirm",
                json={"identifier": "noticed@example.com", "code": outbox.code(), "new_password": "third-pass1"})
    assert "email 驗證碼重設" in _notices(outbox)[-1][2]

    db.add(models.User(username="Boss", hashed_password=get_password_hash(PASSWORD)))
    db.commit()
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, admin_usernames=frozenset({"boss"})))
    boss = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": "Boss", "password": PASSWORD}).json()["access_token"]}
    assert client.post("/api/admin/reset-password", headers=boss, json={"username": "Noticed"}).status_code == 200
    assert "管理員產生臨時密碼" in _notices(outbox)[-1][2]
    assert len(_notices(outbox)) == 3


def test_no_notice_without_an_email_and_mail_failures_do_not_block_the_change(client, outbox):
    _account(client, "Quiet")
    assert client.post("/api/auth/change-password", json={
        "username": "Quiet", "old_password": PASSWORD, "new_password": "second-pass"}).status_code == 200
    assert _notices(outbox) == []

    headers = _account(client, "Loud")
    _bind(client, outbox, headers, "loud@example.com")
    outbox.fail = True
    changed = client.post("/api/auth/change-password", json={
        "username": "Loud", "old_password": PASSWORD, "new_password": "second-pass"})
    assert changed.status_code == 200, "a failed notice never undoes or fails the change"
    wrong = client.post("/api/auth/change-password", json={
        "username": "Loud", "old_password": "wrong-pass", "new_password": "third-pass1"})
    assert wrong.status_code == 401
