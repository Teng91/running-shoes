"""Test-only token signing; production code always passes the app's injected key."""

from backend import credentials
from backend.settings import default_secret_key


def create_access_token(data: dict, *, secret_key: str | None = None) -> str:
    """Sign a token with ``secret_key`` or, by default, the environment's signing key."""
    return credentials.create_access_token(data, secret_key=secret_key or default_secret_key())
