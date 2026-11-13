"""HTTP bearer authentication against the application's injected signing secret."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from backend import credentials as credential_codec
from backend.dependencies import get_db
from backend.models import User

security = HTTPBearer()


def decode_access_token(token: str, *, secret_key: str) -> dict:
    """Decode with the application's injected key; invalid tokens become HTTP 401."""
    try:
        return credential_codec.decode_access_token(token, secret_key=secret_key)
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
