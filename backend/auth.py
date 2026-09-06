import os
import sys
import warnings
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User

SECRET_KEY: str = os.environ.get("SECRET_KEY") or ""
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Detect production-like environments (not local dev)
IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development").lower() != "development"
if not SECRET_KEY:
    if IS_PRODUCTION:
        print("ERROR: SECRET_KEY environment variable is required in production", file=sys.stderr)
        sys.exit(1)
    # Development fallback — still warn but allow startup
    SECRET_KEY = "dev-only-fallback-change-me"
    warnings.warn(
        "Using fallback SECRET_KEY — set the SECRET_KEY env var in production!",
        stacklevel=2,
    )

security = HTTPBearer()


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


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)
    username: str | None = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if payload.get("token_version", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="Session expired; please log in again")
    return user
