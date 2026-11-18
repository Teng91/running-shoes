"""Application middleware that is independent from the composition root."""

from typing import ClassVar

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.settings import megabytes_label

# Applied to every HTTP response (SPEC-054). The page's script/style policy is a
# build-time <meta> CSP in index.html because it carries hashes of the shell's
# inline scripts; these header-only directives cannot be delivered by <meta>.
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", b"frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    # SPEC-071: browsers only honour this over HTTPS; Fly already redirects HTTP.
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
)


class SecurityHeadersMiddleware:
    """Add browser hardening headers without overriding ones a response already set."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _value in headers}
                headers.extend(item for item in SECURITY_HEADERS if item[0] not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class UploadLimitMiddleware:
    """Reject oversized Strava CSV and backup-restore bodies before form parsing/spooling."""

    _paths: ClassVar[frozenset[str]] = frozenset({
        "/api/runs/import/strava",
        "/api/runs/import/strava/preview",
        "/api/account-restore/preview",
    })

    def __init__(self, app: ASGIApp, max_bytes: int, max_backup_bytes: int):
        self.app = app
        self.max_bytes = max_bytes
        self.max_backup_bytes = max_backup_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in self._paths
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        is_backup = scope.get("path") == "/api/account-restore/preview"
        max_bytes = self.max_backup_bytes if is_backup else self.max_bytes
        detail = (
            f"備份不可超過 {megabytes_label(max_bytes)}" if is_backup
            else f"Strava 上傳請求不可超過 {megabytes_label(max_bytes)}"
        )
        content_length = headers.get(b"content-length", b"")
        try:
            declared_size = int(content_length) if content_length else None
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > max_bytes:
            await JSONResponse(
                {"detail": detail, "error": {"code": "too_large", "message": detail}}, status_code=413
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
            if len(body) > max_bytes:
                await JSONResponse(
                    {"detail": detail, "error": {"code": "too_large", "message": detail}}, status_code=413
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        # Hand the body over once and drop this reference, so the request does not keep
        # an extra copy of an upload of up to max_bytes while it is being processed.
        pending = [bytes(body)]
        del body

        async def replay_receive() -> Message:
            if pending:
                return {"type": "http.request", "body": pending.pop(), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)
