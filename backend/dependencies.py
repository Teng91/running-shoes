"""Request-scoped runtime dependencies owned by the HTTP composition layer."""

from typing import Annotated

from fastapi import Header, Request

from backend.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings




OperationKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=16,
                                          max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
