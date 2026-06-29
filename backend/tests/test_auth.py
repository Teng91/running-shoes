from backend.auth import verify_password, get_password_hash, create_access_token, decode_access_token


def test_password_hash_and_verify():
    hashed = get_password_hash("mypassword")
    assert hashed != "mypassword"
    assert verify_password("mypassword", hashed)
    assert not verify_password("wrongpassword", hashed)


def test_create_and_decode_token():
    token = create_access_token(data={"sub": "alice"})
    payload = decode_access_token(token)
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_decode_invalid_token():
    from fastapi import HTTPException
    try:
        decode_access_token("invalid.token.here")
        assert False, "Should have raised"
    except HTTPException as e:
        assert e.status_code == 401
