import pytest
from fastapi import HTTPException

from backend.auth import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


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
    payload = decode_access_token(token)
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_decode_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token("invalid.token.here")

    assert exc_info.value.status_code == 401
