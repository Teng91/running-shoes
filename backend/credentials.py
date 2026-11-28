"""Password and token primitives, independent of HTTP and application globals."""
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
# SPEC-143: a session can be renewed while it is valid, but never past this many days after
# the password was entered, so a copied token cannot be kept alive forever.
SESSION_MAX_AGE_DAYS = 30

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8") if isinstance(hashed_password, str) else hashed_password,
        )
    except (TypeError, ValueError):
        return False


def get_password_hash(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("password must be at most 72 UTF-8 bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, *, secret_key: str, now: datetime | None = None) -> str:
    """Sign ``data`` for 7 days; ``auth_time`` (when the password was entered) defaults to now."""
    current = now or datetime.now(UTC)
    to_encode = {"auth_time": int(current.timestamp()), **data}
    expire = current + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    cap = datetime.fromtimestamp(to_encode["auth_time"], UTC) + timedelta(days=SESSION_MAX_AGE_DAYS)
    to_encode["exp"] = min(expire, cap)
    return jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)


def session_started_at(claims: dict) -> int:
    """When the token's session signed in; tokens issued before SPEC-143 count from exp - 7 days."""
    auth_time = claims.get("auth_time")
    if isinstance(auth_time, int) and not isinstance(auth_time, bool):
        return auth_time
    return int(claims.get("exp", 0)) - ACCESS_TOKEN_EXPIRE_MINUTES * 60


def decode_access_token(token: str, *, secret_key: str) -> dict:
    return jwt.decode(token, secret_key, algorithms=[ALGORITHM])
