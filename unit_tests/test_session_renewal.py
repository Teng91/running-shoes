"""SPEC-143: a valid session can be renewed, never past 30 days after the password was entered."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from backend import credentials
from backend.dependencies import get_db
from backend.main import app
from backend.settings import default_secret_key
from unit_tests.token_helpers import create_access_token, token_for


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def claims(token: str) -> dict:
    return jwt.decode(token, default_secret_key(), algorithms=[credentials.ALGORITHM])


def renew(client, token: str):
    return client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {token}"})


def test_login_tokens_record_when_the_password_was_entered(client):
    assert client.post("/api/auth/register", json={"username": "renewer", "password": "pass1234"}).status_code == 200
    before = int(datetime.now(UTC).timestamp())
    token = client.post("/api/auth/login", json={"username": "renewer", "password": "pass1234"}).json()["access_token"]
    issued = claims(token)
    assert before <= issued["auth_time"] <= issued["exp"] - credentials.ACCESS_TOKEN_EXPIRE_MINUTES * 60 + 1


def test_renewal_keeps_the_identity_and_the_sign_in_time(client, user_with_token):
    user, _ = user_with_token
    signed_in = datetime.now(UTC) - timedelta(days=5)
    old = credentials.create_access_token(
        {"sub": user.username, "token_version": user.token_version, "aid": user.backup_id,
         "auth_time": int(signed_in.timestamp())}, secret_key=default_secret_key(), now=signed_in)
    response = renew(client, old)
    assert response.status_code == 200
    renewed = claims(response.json()["access_token"])
    assert (renewed["sub"], renewed["token_version"], renewed["aid"], renewed["auth_time"]) == (
        user.username, user.token_version, user.backup_id, int(signed_in.timestamp()))
    assert renewed["exp"] > claims(old)["exp"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}).json()[
        "username"] == user.username


def test_renewal_never_extends_a_session_past_30_days(client, user_with_token):
    user, _ = user_with_token
    signed_in = datetime.now(UTC) - timedelta(days=28)
    old = create_access_token({"sub": user.username, "token_version": user.token_version, "aid": user.backup_id,
                               "auth_time": int(signed_in.timestamp())})
    renewed = claims(renew(client, old).json()["access_token"])
    assert renewed["exp"] == int((signed_in + timedelta(days=credentials.SESSION_MAX_AGE_DAYS)).timestamp())


def test_tokens_issued_before_renewal_count_from_their_expiry(client, user_with_token):
    user, _ = user_with_token
    legacy = jwt.encode({"sub": user.username, "token_version": user.token_version, "aid": user.backup_id,
                         "exp": datetime.now(UTC) + timedelta(days=2)}, default_secret_key(),
                        algorithm=credentials.ALGORITHM)
    renewed = claims(renew(client, legacy).json()["access_token"])
    assert renewed["auth_time"] == claims(legacy)["exp"] - credentials.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_revoked_expired_or_missing_tokens_cannot_be_renewed(client, db, user_with_token):
    user, token = user_with_token
    expired = jwt.encode({"sub": user.username, "token_version": user.token_version, "aid": user.backup_id,
                          "exp": datetime.now(UTC) - timedelta(seconds=1)}, default_secret_key(),
                         algorithm=credentials.ALGORITHM)
    assert renew(client, expired).status_code == 401
    assert client.post("/api/auth/refresh").status_code in {401, 403}
    user.token_version += 1  # logout-all / password change
    db.commit()
    assert renew(client, token).status_code == 401
    assert renew(client, token_for(user)).status_code == 200
