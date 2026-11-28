"""SPEC-142: every /api/ request body is bounded before JSON parsing."""

import asyncio
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import schemas
from backend.app_factory import create_app
from backend.middleware import UploadLimitMiddleware
from backend.settings import settings


@pytest.fixture
def client(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>shell</title>", encoding="utf-8")
    config = replace(settings, seed_data=False, frontend_dir=frontend, max_api_body_bytes=4096)
    app = create_app(config, db_engine=engine, session_factory=sessionmaker(bind=engine))
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def test_an_oversized_json_body_is_rejected_before_parsing(client):
    body = json.dumps({"username": "x" * 8192, "password": "secret"})
    response = client.post("/api/auth/login", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"] == {"code": "too_large", "message": "請求內容不可超過 0.00390625 MB"}
    assert response.headers["x-request-id"]
    # A body under the limit still reaches validation.
    assert client.post("/api/auth/login", json={}).status_code == 422


def test_reads_and_upload_routes_keep_their_own_rules(client):
    assert client.get("/api/shoes/active").status_code in {401, 403}
    # The Strava preview keeps its larger upload limit: 8 KB passes the size guard and
    # reaches the route (which rejects the malformed form itself).
    response = client.post(
        "/api/runs/import/strava/preview", content=b"x" * 8192,
        headers={"content-type": "multipart/form-data; boundary=x"},
    )
    assert response.status_code == 400


def run_middleware(scope, messages, max_api_bytes=10):
    incoming = iter(messages)
    sent: list[dict] = []
    seen: list[dict] = []

    async def receive():
        return next(incoming)

    async def send(message):
        sent.append(message)

    async def downstream(_scope, limited_receive, _send):
        while True:
            message = await limited_receive()
            seen.append(message)
            if message["type"] == "http.disconnect":
                return

    middleware = UploadLimitMiddleware(downstream, max_bytes=100, max_backup_bytes=100,
                                       max_api_bytes=max_api_bytes)
    asyncio.run(middleware(scope, receive, send))
    return sent, seen


def test_a_chunked_json_body_without_content_length_is_counted():
    scope = {"type": "http", "method": "PUT", "path": "/api/goals", "headers": []}
    sent, seen = run_middleware(scope, [
        {"type": "http.request", "body": b"123456", "more_body": True},
        {"type": "http.request", "body": b"789012", "more_body": False},
    ])
    assert sent[0]["status"] == 413 and seen == []


def test_after_the_body_the_route_waits_for_the_real_disconnect():
    """Streamed answers (agent chat, reports) listen for the client's disconnect."""
    scope = {"type": "http", "method": "POST", "path": "/api/agent/chat/stream", "headers": []}
    real_disconnect = {"type": "http.disconnect", "source": "client"}
    sent, seen = run_middleware(scope, [
        {"type": "http.request", "body": b"{}", "more_body": False},
        real_disconnect,
    ])
    assert sent == []
    assert seen == [{"type": "http.request", "body": b"{}", "more_body": False}, real_disconnect]


def test_the_largest_valid_chat_request_fits_the_default_limit():
    """The limit never rejects a request the schemas accept (CJK text is 3 UTF-8 bytes)."""
    turn = "跑" * 3_000
    payload = {"user_message": "跑" * 12_000, "model": "m" * 200,
               "history": [{"role": "user", "content": turn}] * 16}
    request = schemas.AgentChatRequest.model_validate(payload)
    assert len(request.user_message) + sum(len(item.content) for item in request.history) == 60_000
    worst_case = json.dumps(payload).encode("utf-8")  # \\uXXXX escapes: 6 bytes per character
    assert len(worst_case) < settings.max_api_body_bytes
