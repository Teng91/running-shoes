"""Application middleware that is independent from the composition root."""

from typing import ClassVar

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.settings import settings

MAX_STRAVA_REQUEST_BYTES = settings.max_strava_request_bytes


class StravaUploadLimitMiddleware:
    """Reject oversized Strava multipart bodies before form parsing/spooling."""

    _paths: ClassVar[frozenset[str]] = frozenset({
        "/api/runs/import/strava",
        "/api/runs/import/strava/preview",
    })

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in self._paths
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length", b"")
        try:
            declared_size = int(content_length) if content_length else None
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > MAX_STRAVA_REQUEST_BYTES:
            await JSONResponse(
                {"detail": "Strava 上傳請求不可超過 11 MB"}, status_code=413
            )(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > MAX_STRAVA_REQUEST_BYTES:
                await JSONResponse(
                    {"detail": "Strava 上傳請求不可超過 11 MB"}, status_code=413
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)
