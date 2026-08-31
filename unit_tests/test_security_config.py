"""Deployment and frontend guards for security-sensitive configuration."""

import tomllib
from pathlib import Path

from sqlalchemy import text

from backend.database import engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_fly_deployment_enables_production_secret_checks():
    config = tomllib.loads((PROJECT_ROOT / "fly.toml").read_text(encoding="utf-8"))

    assert config["env"]["ENVIRONMENT"] == "production"


def test_sqlite_foreign_keys_are_enabled():
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_agent_frontend_handles_http_auth_and_non_sse_errors_before_streaming():
    source = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    fetch_start = source.index("const res = await fetch(API_BASE + '/agent/chat/stream'")
    reader_start = source.index("const reader = res.body.getReader()", fetch_start)
    guarded_section = source[fetch_start:reader_start]

    assert "res.status === 401" in guarded_section
    assert "!res.ok" in guarded_section
    assert "text/event-stream" in guarded_section
    assert "!res.body" in guarded_section


def test_agent_frontend_distinguishes_failed_tools_from_completed_tools():
    source = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "event.ok === false" in source
    assert "tool-item.failed" in source
    assert "搜尋服務暫時無法" not in source  # message comes from the backend event


def test_agent_frontend_always_discloses_web_search_usage():
    source = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "webSearchAttempted" in source
    assert "webSearchSucceeded" in source
    assert "本輪已即時搜尋" in source
    assert "本輪使用近期網路搜尋快取" in source
    assert "本輪不需要網路搜尋" in source
    assert "網路搜尋失敗，本則回答沒有可驗證的即時網路資料" in source
    assert "event.type === 'source_summary'" in source
    assert "url.protocol !== 'http:' && url.protocol !== 'https:'" in source
    assert "link.rel = 'noopener noreferrer'" in source


def test_run_log_frontend_keeps_daily_ticks_and_select_state_safe():
    source = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "autoSkip: false" in source
    assert "id === 'edit-run-shoe' && selectedId !== null" in source
    assert "原鞋款已刪除，請重新選擇" in source
    assert "document.getElementById('run-date').value = localDateISO()" in source
    assert "document.getElementById('run-month').value = localDateISO().slice(0, 7)" in source


def test_strava_upload_lets_browser_set_multipart_content_type():
    source = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    upload_source = source.split("async function apiUpload", 1)[1].split(
        "// ====== Auth Handlers ======", 1
    )[0]

    assert "new FormData()" in upload_source
    assert "headers: authHeaders()" not in upload_source
    assert "headers['Authorization']" in upload_source


def test_strava_frontend_uses_account_range_and_opt_in_mileage_sync():
    source = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "strava-import-range:${currentUser" in source
    assert 'id="strava-start-date" type="date" value=' not in source
    assert 'id="strava-end-date" type="date" value=' not in source
    assert 'id="strava-sync-mileage" type="checkbox"' in source
    assert "sync_shoe_mileage: String(syncShoeMileage)" in source
