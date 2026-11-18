"""Shared request throttling for authentication, LLM-backed endpoints and backup previews.

Every limit is a fixed window stored in SQLite (``rate_limit_buckets``), so all
workers share one budget. Limits come from the application's injected settings.
Each check runs on its own short transaction from the application engine: the
request's session is never committed as a side effect, and all windows touched by
one request are consumed atomically. A rejected request records nothing, so a
client that is over its own limit never spends a shared (global) budget.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import ip_address

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from backend.settings import DAILY_WINDOW_SECONDS, RATE_LIMIT_BUCKET_RETENTION_SECONDS, Settings

# Failed password checks. A per-address lock alone still allows distributed
# guessing, and a per-account lock alone lets anyone lock a known username out.
# Lock one address after LOGIN_FAILURE_LIMIT failures for an account, and the
# account everywhere only after ACCOUNT_FAILURE_LIMIT failures from many addresses.
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
LOGIN_FAILURE_LIMIT = 10
ACCOUNT_FAILURE_LIMIT = 100
STALE_BUCKET_SECONDS = RATE_LIMIT_BUCKET_RETENTION_SECONDS

_AUTH_IP_DETAIL = "驗證請求過於頻繁，請稍後再試。"
_AUTH_GLOBAL_DETAIL = "驗證服務目前忙碌，請稍後再試。"
_AGENT_IP_DETAIL = "此網路的 AI 請求過於頻繁，請稍後再試。"
_AGENT_USER_DETAIL = "AI 請求過於頻繁，請稍後再試。"
_AGENT_GLOBAL_DETAIL = "AI 服務目前忙碌，請稍後再試。"
_AGENT_USER_DAILY_DETAIL = "今天的 AI 使用次數已達上限，請明天再試。"
_AGENT_GLOBAL_DAILY_DETAIL = "今天全站的 AI 使用額度已用完，請明天再試。"
_REFRESH_USER_DETAIL = "模型列表剛更新過，請稍後再試。"
_REFRESH_GLOBAL_DETAIL = "模型列表更新目前忙碌，請稍後再試。"
_LOGIN_FAILURE_DETAIL = "此帳號登入失敗次數過多，請 15 分鐘後再試。"
_RESTORE_USER_DETAIL = "備份預覽過於頻繁，請稍後再試。"
_RESTORE_GLOBAL_DETAIL = "備份還原服務目前忙碌，請稍後再試。"


@dataclass(frozen=True)
class Window:
    scope: str
    key: str
    limit: int
    detail: str
    seconds: int = 60


def _runtime(request: Request) -> tuple[Settings, Engine]:
    state = request.app.state
    return state.settings, state.db_engine


def client_key(request: Request, settings: Settings) -> str:
    """Trust Fly's client-IP header only when running behind Fly's proxy."""
    fly_ip = request.headers.get("fly-client-ip", "").strip()
    if settings.is_fly_runtime and fly_ip:
        try:
            return str(ip_address(fly_ip))
        except ValueError:
            pass
    return (request.client.host if request.client else "unknown")[:64]


def _rejection(window: Window, started: float | None, now: float) -> HTTPException:
    elapsed = now - started if started is not None else 0
    return HTTPException(
        status_code=429,
        detail=window.detail,
        headers={"Retry-After": str(max(1, int(window.seconds - elapsed)))},
    )


def _bucket_start(connection: Connection, window: Window) -> float | None:
    return connection.execute(
        text("SELECT window_started FROM rate_limit_buckets WHERE scope = :scope AND bucket_key = :key"),
        {"scope": window.scope, "key": window.key[:128]},
    ).scalar_one_or_none()


def _take(connection: Connection, window: Window, now: float) -> bool:
    """Record one event in a fixed window; False (and no change) when it is full."""
    recorded = connection.execute(
        text("""
            INSERT INTO rate_limit_buckets (scope, bucket_key, window_started, event_count)
            VALUES (:scope, :key, :now, 1)
            ON CONFLICT(scope, bucket_key) DO UPDATE SET
                window_started = CASE WHEN rate_limit_buckets.window_started <= :cutoff
                    THEN :now ELSE rate_limit_buckets.window_started END,
                event_count = CASE WHEN rate_limit_buckets.window_started <= :cutoff
                    THEN 1 ELSE rate_limit_buckets.event_count + 1 END
            WHERE rate_limit_buckets.window_started <= :cutoff
               OR rate_limit_buckets.event_count < :limit
            RETURNING window_started
        """),
        {"scope": window.scope, "key": window.key[:128], "now": now,
         "cutoff": now - window.seconds, "limit": window.limit},
    ).scalar_one_or_none()
    return recorded is not None


def consume(engine: Engine, windows: Sequence[Window], now: float | None = None) -> None:
    """Record one event in every window, or none of them if any window is full."""
    current = time.time() if now is None else now
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM rate_limit_buckets WHERE window_started <= :stale"),
            {"stale": current - STALE_BUCKET_SECONDS},
        )
        for window in windows:
            if not _take(connection, window, current):
                # Raising rolls back every window already taken in this transaction.
                raise _rejection(window, _bucket_start(connection, window), current)


def reject_if_full(engine: Engine, windows: Sequence[Window], now: float | None = None) -> None:
    """Read-only check; never creates or increments a bucket."""
    current = time.time() if now is None else now
    with engine.connect() as connection:
        for window in windows:
            row = connection.execute(
                text("SELECT window_started, event_count FROM rate_limit_buckets "
                     "WHERE scope = :scope AND bucket_key = :key"),
                {"scope": window.scope, "key": window.key[:128]},
            ).first()
            if row is not None and row[0] > current - window.seconds and row[1] >= window.limit:
                raise _rejection(window, row[0], current)


def enforce_auth_rate_limit(request: Request) -> None:
    settings, engine = _runtime(request)
    consume(engine, (
        Window("auth-ip", client_key(request, settings), settings.auth_rate_limit_per_minute, _AUTH_IP_DETAIL),
        Window("auth-global", "global", settings.auth_global_rate_limit_per_minute, _AUTH_GLOBAL_DETAIL),
    ))


def enforce_agent_request_limits(request: Request, user_id: int) -> None:
    settings, engine = _runtime(request)
    consume(engine, (
        Window("agent-ip", client_key(request, settings), settings.agent_ip_rate_limit_per_minute,
               _AGENT_IP_DETAIL),
        Window("agent-user", str(user_id), settings.agent_rate_limit_per_minute, _AGENT_USER_DETAIL),
        Window("agent-global", "global", settings.agent_global_rate_limit_per_minute, _AGENT_GLOBAL_DETAIL),
        # SPEC-071: daily budgets, so an open registration cannot drain the provider credit.
        Window("agent-user-daily", str(user_id), settings.agent_daily_limit_per_user,
               _AGENT_USER_DAILY_DETAIL, seconds=DAILY_WINDOW_SECONDS),
        Window("agent-global-daily", "global", settings.agent_global_daily_limit,
               _AGENT_GLOBAL_DAILY_DETAIL, seconds=DAILY_WINDOW_SECONDS),
    ))


def enforce_model_refresh_limits(request: Request, user_id: int) -> None:
    """Account cooldown and global refresh budget, consumed together or not at all."""
    settings, engine = _runtime(request)
    consume(engine, (
        Window("model-refresh-user", str(user_id), 1, _REFRESH_USER_DETAIL,
               seconds=settings.model_refresh_cooldown_seconds),
        Window("model-refresh-global", "global", settings.model_refresh_global_per_minute,
               _REFRESH_GLOBAL_DETAIL),
    ))


def enforce_restore_preview_limits(request: Request, user_id: int) -> None:
    """Parsing an uploaded backup is the most memory-hungry request; bound how often it runs."""
    settings, engine = _runtime(request)
    consume(engine, (
        Window("restore-preview-user", str(user_id), settings.restore_preview_rate_limit_per_minute,
               _RESTORE_USER_DETAIL),
        Window("restore-preview-global", "global", settings.restore_preview_global_rate_limit_per_minute,
               _RESTORE_GLOBAL_DETAIL),
    ))


def _login_failure_windows(request: Request, settings: Settings, username: str) -> tuple[Window, Window]:
    return (
        Window("auth-failure-client", f"{client_key(request, settings)}|{username}", LOGIN_FAILURE_LIMIT,
               _LOGIN_FAILURE_DETAIL, seconds=LOGIN_FAILURE_WINDOW_SECONDS),
        Window("auth-failure-account", username, ACCOUNT_FAILURE_LIMIT,
               _LOGIN_FAILURE_DETAIL, seconds=LOGIN_FAILURE_WINDOW_SECONDS),
    )


def reject_locked_account(request: Request, username: str) -> None:
    settings, engine = _runtime(request)
    reject_if_full(engine, _login_failure_windows(request, settings, username))


def record_login_failure(request: Request, username: str) -> None:
    """Count a failed password check; a full window simply stops counting."""
    settings, engine = _runtime(request)
    current = time.time()
    with engine.begin() as connection:
        for window in _login_failure_windows(request, settings, username):
            _take(connection, window, current)
