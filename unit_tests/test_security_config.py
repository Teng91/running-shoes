"""Deployment and frontend guards for security-sensitive configuration."""

import tomllib
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import rate_limits
from backend.app_factory import http_exception_handler
from backend.database import configure_sqlite_connection

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SOURCE = "\n".join(
    (PROJECT_ROOT / "frontend" / name).read_text(encoding="utf-8")
    for name in (
        "index.html",
        "styles.css",
        "app-boot.js",
        "app-state.js",
        "app-api.js",
        "app-auth.js",
        "app-streams.js",
        "app-core.js",
        "app-agent.js",
        "app-reports.js",
        "app-runs.js",
        "app-strava.js",
        "app-run-insights.js",
        "app-shoes.js",
        "app-dashboard.js",
        "app-monthly.js",
        "app-exports.js",
        "app-goals.js",
        "app-charts.js",
        "app-shoe-charts.js",
        "app-monthly-charts.js",
        "app-spending.js",
        "app.js",
    )
)


def test_fly_deployment_enables_production_secret_checks():
    config = tomllib.loads((PROJECT_ROOT / "fly.toml").read_text(encoding="utf-8"))

    assert config["env"]["ENVIRONMENT"] == "production"
    assert config["env"].get("SEED_DATA") != "true"


def test_client_ip_header_is_only_trusted_on_fly(monkeypatch):
    request = SimpleNamespace(
        headers={"fly-client-ip": "198.51.100.9"},
        client=SimpleNamespace(host="203.0.113.7"),
    )
    monkeypatch.setattr(rate_limits, "IS_FLY_RUNTIME", False)
    assert rate_limits._client_key(request) == "203.0.113.7"

    monkeypatch.setattr(rate_limits, "IS_FLY_RUNTIME", True)
    assert rate_limits._client_key(request) == "198.51.100.9"
    request.headers["fly-client-ip"] = "not-an-ip"
    assert rate_limits._client_key(request) == "203.0.113.7"


def test_docker_enables_production_secret_checks():
    source = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV ENVIRONMENT=production" in source


def test_sqlite_foreign_keys_are_enabled():
    test_engine = create_engine("sqlite://")
    event.listen(
        test_engine,
        "connect",
        lambda dbapi_connection, _record: configure_sqlite_connection(dbapi_connection),
    )
    with test_engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_http_exception_handler_preserves_protocol_headers():
    test_app = FastAPI()
    test_app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )

    @test_app.get("/limited")
    def limited():
        raise HTTPException(
            status_code=429,
            detail="slow down",
            headers={"Retry-After": "42"},
        )

    response = TestClient(test_app).get("/limited")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"


def test_agent_frontend_handles_http_auth_and_non_sse_errors_before_streaming():
    source = FRONTEND_SOURCE

    fetch_start = source.index(
        "const res = await authenticatedFetch(API_BASE + '/agent/chat/stream'"
    )
    reader_start = source.index("readJsonEventStream(res", fetch_start)
    guarded_section = source[fetch_start:reader_start]

    adapter = (PROJECT_ROOT / "frontend/app-api.js").read_text(encoding="utf-8")
    guard = adapter[adapter.index("async function authenticatedFetch"):]
    guard = guard[:guard.index("async function readAuthenticatedBody")]
    assert guard.index("requireAuthSession(session);") < guard.index("response.status === 401")
    assert "clearAuth();" in guard
    assert "showLoginView();" in guard
    assert "isCurrentRequest()" in guarded_section
    stream_adapter = (PROJECT_ROOT / "frontend/app-streams.js").read_text(encoding="utf-8")
    assert stream_adapter.index("!response.ok") < stream_adapter.index("response.body.getReader()")
    assert "text/event-stream" in stream_adapter
    assert "!response.body" in stream_adapter


def test_agent_frontend_distinguishes_failed_tools_from_completed_tools():
    source = FRONTEND_SOURCE

    assert "event.ok === false" in source
    assert "tool-item.failed" in source
    assert "搜尋服務暫時無法" not in source  # message comes from the backend event


def test_agent_frontend_always_discloses_web_search_usage():
    source = FRONTEND_SOURCE

    assert "webSearchAttempted" in source
    assert "webSearchSucceeded" in source
    assert "本輪已即時搜尋" in source
    assert "本輪使用近期網路搜尋快取" in source
    assert "本輪不需要網路搜尋" in source
    assert "網路搜尋失敗，本則回答沒有可驗證的即時網路資料" in source
    assert "event.type === 'source_summary'" in source
    assert "url.protocol !== 'http:' && url.protocol !== 'https:'" in source
    assert "link.rel = 'noopener noreferrer'" in source


def test_run_log_frontend_keeps_calendar_actions_and_select_state_safe():
    source = FRONTEND_SOURCE

    assert 'id="run-calendar"' in source
    assert "Array.from({length:daysInMonth}" in source
    assert "selectRunCalendarDate('${date}',event)" in source
    assert "event.stopPropagation();openRunModal(${run.id})" in source
    assert 'id="run-shoe-legend"' in source
    assert "percentage.toFixed(1)" in source
    assert "km.toFixed(2)} km" in source
    assert "formatDate(next) <= today" in source
    assert "nextStart ? today" in source
    assert "async function loadStravaHistory()" in source
    assert "await apiGet('/runs/import/strava/history')" in source
    assert "載入 Strava 匯入歷史失敗:" in source
    assert "id === 'edit-run-shoe' && selectedId !== null" in source
    assert "原鞋款已刪除，請重新選擇" in source
    assert "document.getElementById('run-date').value = today" in source
    assert "document.getElementById('run-date').max = today" in source
    assert "document.getElementById('edit-run-date').max = today" in source
    assert "跑步日期不可晚於今天" in source
    assert "document.getElementById('run-month').value = localDateISO().slice(0, 7)" in source


def test_strava_upload_lets_browser_set_multipart_content_type():
    upload_source = (PROJECT_ROOT / "frontend" / "app-api.js").read_text(
        encoding="utf-8"
    ).split("async function apiUpload", 1)[1]

    assert "new FormData()" in upload_source
    assert "headers: authHeaders()" not in upload_source
    assert "headers['Authorization']" in upload_source


def test_strava_frontend_uses_account_range_and_automatic_mileage_sync():
    source = FRONTEND_SOURCE

    assert "strava-import-range:${currentUser" in source
    assert 'id="strava-start-date" type="date" value=' not in source
    assert 'id="strava-end-date" type="date" value=' not in source
    assert 'id="strava-sync-mileage"' not in source
    assert "sync_shoe_mileage" not in source
    assert "只有新活動會加入跑鞋里程與對應月份的月跑量" in source


def test_run_log_is_the_first_and_default_tab():
    source = FRONTEND_SOURCE
    tabs = source.split('<div class="tabs"', 1)[1].split("</div>", 1)[0]

    assert tabs.index('data-tab="runs"') < tabs.index('data-tab="shoes"')
    assert 'class="tab active"' in tabs
    assert 'data-tab="runs"' in tabs
    assert "tab.dataset.tab === 'runs'" in source


def test_strava_frontend_discards_stale_preview_responses():
    source = FRONTEND_SOURCE

    assert "new AbortController()" in source
    assert "requestId !== stravaPreviewRequestId" in source
    assert "stravaPreviewKey !== stravaInputKey" in source
    assert "file.size > 10 * 1024 * 1024" in source
