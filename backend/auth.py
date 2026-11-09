"""HTTP bearer authentication against the application's injected signing secret."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from backend import credentials as credential_codec
from backend.credentials import ACCESS_TOKEN_EXPIRE_MINUTES as ACCESS_TOKEN_EXPIRE_MINUTES
from backend.credentials import ALGORITHM as ALGORITHM
from backend.credentials import get_password_hash as get_password_hash
from backend.credentials import verify_password as verify_password
from backend.dependencies import get_db
from backend.models import User
from backend.settings import default_secret_key

security = HTTPBearer()


def create_access_token(data: dict, *, secret_key: str | None = None) -> str:
    """Sign a token; without an explicit key, use the environment's default key."""
    return credential_codec.create_access_token(data, secret_key=secret_key or default_secret_key())


def decode_access_token(token: str, *, secret_key: str | None = None) -> dict:
    try:
        return credential_codec.decode_access_token(token, secret_key=secret_key or default_secret_key())
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
        credentials.credentials, secret_key=request.app.state.settings.secret_key
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
