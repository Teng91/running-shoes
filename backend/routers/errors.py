"""Translate application errors at the HTTP boundary."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

from backend.services.errors import (
    CapacityExceeded,
    Conflict,
    DomainError,
    Invalid,
    NotFound,
    Unauthorized,
)


@contextmanager
def service_errors() -> Iterator[None]:
    try:
        yield
    except DomainError as error:
        status = {NotFound: 404, Invalid: 400, Conflict: 409, Unauthorized: 401, CapacityExceeded: 403}[type(error)]
        raise HTTPException(status_code=status, detail=str(error)) from error
