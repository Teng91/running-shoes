import pytest
from fastapi import HTTPException

from backend.auth import decode_access_token
from backend.credentials import get_password_hash, verify_password
from backend.settings import default_secret_key
from unit_tests.token_helpers import create_access_token


def test_password_hash_and_verify():
    hashed = get_password_hash("mypassword")
    assert hashed != "mypassword"
    assert verify_password("mypassword", hashed)
    assert not verify_password("wrongpassword", hashed)


def test_bcrypt_helpers_handle_overlong_utf8_passwords_safely():
    hashed = get_password_hash("valid-password")
    assert verify_password("密" * 25, hashed) is False
    with pytest.raises(ValueError, match="72 UTF-8 bytes"):
        get_password_hash("密" * 25)


def test_create_and_decode_token():
    token = create_access_token(data={"sub": "alice"})
    payload = decode_access_token(token, secret_key=default_secret_key())
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_decode_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token("invalid.token.here", secret_key=default_secret_key())

    assert exc_info.value.status_code == 401


def test_http_auth_never_signs_or_decodes_with_an_implicit_key():
    """SPEC-053: production auth uses only the app's injected key; test signing lives in token_helpers."""
    import inspect

    from backend import auth

    assert not hasattr(auth, "create_access_token")
    assert not hasattr(auth, "get_password_hash")
    parameter = inspect.signature(auth.decode_access_token).parameters["secret_key"]
    assert parameter.default is inspect.Parameter.empty
    token = create_access_token({"sub": "alice"}, secret_key="k" * 32)
    with pytest.raises(HTTPException):
        decode_access_token(token, secret_key=default_secret_key())
    assert decode_access_token(token, secret_key="k" * 32)["sub"] == "alice"
