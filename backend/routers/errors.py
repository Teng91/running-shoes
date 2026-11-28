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
    Unprocessable,
)


class CodedHTTPException(HTTPException):
    """An HTTP error whose machine-readable ``error.code`` is not implied by the status alone."""

    def __init__(self, status_code: int, detail: str, code: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


@contextmanager
def service_errors() -> Iterator[None]:
    try:
        yield
    except CapacityExceeded as error:
        # SPEC-092: a full registration is a 403 like "Admin only", but clients tell them apart.
        raise CodedHTTPException(403, str(error), "capacity") from error
    except DomainError as error:
        status = {NotFound: 404, Invalid: 400, Conflict: 409, Unauthorized: 401, Unprocessable: 422}[type(error)]
        raise HTTPException(status_code=status, detail=str(error)) from error
