"""SPEC-054 browser hardening headers, same-origin API and the shell's page policy."""

import asyncio
import base64
import hashlib
import mimetypes
import re
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app_factory import create_app
from backend.middleware import SECURITY_HEADERS, SecurityHeadersMiddleware
from backend.settings import settings
from scripts.build_frontend import content_security_policy, frontend_outputs, inline_script_hashes

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_HEADERS = {name.decode(): value.decode() for name, value in SECURITY_HEADERS}


@pytest.fixture
def client(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    frontend = tmp_path / "frontend"
    (frontend / "runtime").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>shell</title>", encoding="utf-8")
    (frontend / "app.js").write_text("window.app = true;", encoding="utf-8")
    (frontend / "runtime" / "module.mjs").write_text("export const ready = true;", encoding="utf-8")
    (frontend / "styles.css").write_text("body{}", encoding="utf-8")
    config = replace(settings, seed_data=False, frontend_dir=frontend, max_strava_csv_bytes=1024)
    app = create_app(config, db_engine=engine, session_factory=sessionmaker(bind=engine))
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def assert_hardened(response) -> None:
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, name


def test_every_response_kind_carries_the_hardening_headers(client):
    assert client.get("/health/live").status_code == 200
    responses = {
        "json": client.get("/health/live"),
        "shell": client.get("/"),
        "spa fallback": client.get("/runs/history"),
        "script": client.get("/app.js"),
        "unauthenticated api": client.get("/api/shoes/active"),
        "unknown api": client.get("/api/does-not-exist"),
        "validation": client.post("/api/auth/login", json={}),
        "upload limit": client.post(
            "/api/runs/import/strava/preview",
            content=b"x" * (1024 * 1024 + 4096),
            headers={"content-type": "multipart/form-data; boundary=x", "content-length": str(1024 * 1024 + 4096)},
        ),
    }
    assert responses["shell"].text.startswith("<!doctype html>")
    assert responses["unauthenticated api"].status_code in {401, 403}
    assert responses["unknown api"].status_code == 404
    assert responses["validation"].status_code == 422
    assert responses["upload limit"].status_code == 413
    for kind, response in responses.items():
        assert response.headers["x-request-id"], kind
        assert_hardened(response)


def test_the_api_is_same_origin_only(client):
    attacker = "https://attacker.example"
    simple = client.get("/health/live", headers={"Origin": attacker})
    preflight = client.options("/api/shoes/active", headers={
        "Origin": attacker,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    })
    for response in (simple, preflight):
        assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-headers" not in response.headers
    assert preflight.status_code in {404, 405}


def test_scripts_and_modules_keep_javascript_media_types_under_nosniff(client):
    assert mimetypes.guess_type("feature.mjs")[0] == "text/javascript"
    for path in ("/app.js", "/runtime/module.mjs"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/javascript"), path
        assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/styles.css").headers["content-type"].startswith("text/css")


def test_security_headers_do_not_override_a_response_that_sets_its_own():
    sent = []

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"X-Frame-Options", b"SAMEORIGIN")]})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    middleware = SecurityHeadersMiddleware(downstream)
    asyncio.run(middleware({"type": "http", "method": "GET", "path": "/"}, receive, send))
    headers = [(name.lower(), value) for name, value in sent[0]["headers"]]
    assert headers.count((b"x-frame-options", b"SAMEORIGIN")) == 1
    assert [name for name, _value in headers].count(b"x-frame-options") == 1
    assert (b"x-content-type-options", b"nosniff") in headers

    lifespan = []

    async def other(scope, receive, send):
        lifespan.append(scope["type"])

    asyncio.run(SecurityHeadersMiddleware(other)({"type": "lifespan"}, receive, send))
    assert lifespan == ["lifespan"]


def test_generated_shell_policy_hashes_exactly_its_inline_scripts():
    html = frontend_outputs()[ROOT / "frontend" / "index.html"]
    policy = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    assert policy and policy.start() < html.index("<script")
    bodies = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    expected = {
        "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
        for body in bodies
    }
    assert set(inline_script_hashes(html)) == expected and len(expected) == len(bodies) == 3
    assert policy.group(1) == content_security_policy(html.replace(policy.group(0), ""))
    assert "'unsafe-inline'" not in policy.group(1).split("script-src", 1)[1].split(";", 1)[0]


def test_inline_scripts_with_attributes_are_rejected_instead_of_silently_unhashed():
    assert inline_script_hashes('<script src="/app.js"></script><script>ok()</script>') == [
        "'sha256-" + base64.b64encode(hashlib.sha256(b"ok()").digest()).decode() + "'"
    ]
    with pytest.raises(ValueError, match="cannot be hashed"):
        inline_script_hashes('<script type="module">import("/x.mjs")</script>')
