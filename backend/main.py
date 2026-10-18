"""ASGI entry point; application composition lives in backend.app_factory."""

from backend.app_factory import create_app

app = create_app()

__all__ = ["app", "create_app"]
