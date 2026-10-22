import sys
import warnings

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from backend import credentials as credential_codec
from backend.credentials import ACCESS_TOKEN_EXPIRE_MINUTES as ACCESS_TOKEN_EXPIRE_MINUTES
from backend.credentials import ALGORITHM as ALGORITHM
from backend.credentials import get_password_hash as get_password_hash
from backend.credentials import verify_password as verify_password
from backend.database import get_db
from backend.models import User
from backend.settings import settings

SECRET_KEY = settings.secret_key

# Detect production-like environments (not local dev)
IS_PRODUCTION = settings.is_production
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


def create_access_token(data: dict, *, secret_key: str | None = None) -> str:
    return credential_codec.create_access_token(data, secret_key=secret_key or SECRET_KEY)


def decode_access_token(token: str, *, secret_key: str | None = None) -> dict:
    try:
        return credential_codec.decode_access_token(token, secret_key=secret_key or SECRET_KEY)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(
        credentials.credentials,
        secret_key=request.app.state.settings.secret_key or SECRET_KEY,
    )
    username: str | None = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if payload.get("token_version", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="Session expired; please log in again")
    return user
