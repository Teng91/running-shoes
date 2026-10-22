"""Request-scoped runtime dependencies owned by the HTTP composition layer."""

from fastapi import Request

from backend.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings
