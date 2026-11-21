"""Test-only token signing; production code always passes the app's injected key."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from backend import credentials
from backend.models import User
from backend.settings import default_secret_key


def create_access_token(data: dict, *, secret_key: str | None = None) -> str:
    """Sign arbitrary claims with ``secret_key`` or, by default, the environment's signing key.

    Since SPEC-093 the API accepts only tokens that name the account (``aid``); use
    ``token_for`` for a working session and this function for malformed or foreign claims.
    """
    return credentials.create_access_token(data, secret_key=secret_key or default_secret_key())


def token_for(user: Any, *, secret_key: str | None = None) -> str:
    """A token like the login endpoint issues for ``user`` (name, session version and account id)."""
    return create_access_token(
        {"sub": user.username, "token_version": user.token_version, "aid": user.backup_id},
        secret_key=secret_key,
    )


def token_for_name(source: Session | Callable[[], Session], username: str, *,
                   secret_key: str | None = None) -> str:
    """``token_for`` the account named ``username``, read from a session or a session factory."""
    if isinstance(source, Session):
        return token_for(source.query(User).filter_by(username=username).one(), secret_key=secret_key)
    with source() as db:
        return token_for(db.query(User).filter_by(username=username).one(), secret_key=secret_key)
