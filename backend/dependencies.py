"""Request-scoped runtime dependencies owned by the HTTP composition layer."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Header, Request
from sqlalchemy.orm import Session

from backend.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    """One session per request from the application's injected session factory."""
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


OperationKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=16,
                                          max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
