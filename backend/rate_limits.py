"""Shared request throttling for authentication and LLM-backed endpoints."""

import time
from collections import deque
from ipaddress import ip_address
from threading import Lock

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import models
from backend.settings import settings

AGENT_RATE_LIMIT_PER_MINUTE = settings.agent_rate_limit_per_minute
AGENT_IP_RATE_LIMIT_PER_MINUTE = settings.agent_ip_rate_limit_per_minute
AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE = settings.agent_global_rate_limit_per_minute
AUTH_RATE_LIMIT_PER_MINUTE = settings.auth_rate_limit_per_minute
AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE = settings.auth_global_rate_limit_per_minute
MODEL_REFRESH_COOLDOWN_SECONDS = settings.model_refresh_cooldown_seconds
MODEL_REFRESH_GLOBAL_PER_MINUTE = settings.model_refresh_global_per_minute
IS_FLY_RUNTIME = settings.is_fly_runtime

_agent_rate_events: dict[int, deque[float]] = {}
_agent_ip_rate_events: dict[str, deque[float]] = {}
_agent_global_rate_events: dict[str, deque[float]] = {}
_auth_rate_events: dict[str, deque[float]] = {}
_auth_global_rate_events: dict[str, deque[float]] = {}
_model_refresh_times: dict[int, float] = {}
_model_refresh_global_events: dict[str, deque[float]] = {}
_agent_rate_lock = Lock()


def _enforce_agent_rate_limit(user_id: int, now: float | None = None) -> None:
    """Apply a per-account sliding-window limit to server-key LLM calls."""
    current = time.monotonic() if now is None else now
    cutoff = current - 60
    with _agent_rate_lock:
        for stale_user_id, stale_events in list(_agent_rate_events.items()):
            while stale_events and stale_events[0] <= cutoff:
                stale_events.popleft()
            if not stale_events:
                _agent_rate_events.pop(stale_user_id, None)
        events = _agent_rate_events.setdefault(user_id, deque())
        if len(events) >= AGENT_RATE_LIMIT_PER_MINUTE:
            retry_after = max(1, int(60 - (current - events[0])))
            raise HTTPException(
                status_code=429,
                detail="AI 請求過於頻繁，請稍後再試。",
                headers={"Retry-After": str(retry_after)},
            )
        events.append(current)


def _client_key(request: Request) -> str:
    """Trust Fly's client-IP header only when running behind Fly's proxy."""
    fly_ip = request.headers.get("fly-client-ip", "").strip()
    if IS_FLY_RUNTIME and fly_ip:
        try:
            return str(ip_address(fly_ip))
        except ValueError:
            pass
    return (request.client.host if request.client else "unknown")[:64]


def _enforce_window_limit(
    buckets: dict[str, deque[float]],
    key: str,
    limit: int,
    detail: str,
    now: float | None = None,
) -> None:
    current = time.monotonic() if now is None else now
    cutoff = current - 60
    with _agent_rate_lock:
        for stale_key, stale_events in list(buckets.items()):
            while stale_events and stale_events[0] <= cutoff:
                stale_events.popleft()
            if not stale_events:
                buckets.pop(stale_key, None)
        events = buckets.setdefault(key, deque())
        if len(events) >= limit:
            retry_after = max(1, int(60 - (current - events[0])))
            raise HTTPException(
                status_code=429,
                detail=detail,
                headers={"Retry-After": str(retry_after)},
            )
        events.append(current)


def _enforce_shared_window_limit(
    db: Session,
    scope: str,
    key: str,
    limit: int,
    detail: str,
    window_seconds: int = 60,
    now: float | None = None,
) -> None:
    """Atomically enforce a fixed window in SQLite so workers share limits."""
    current = time.time() if now is None else now
    cutoff = current - window_seconds
    db.query(models.RateLimitBucket).filter(
        models.RateLimitBucket.window_started <= current - 3600
    ).delete(synchronize_session=False)
    result = db.execute(
        text("""
            INSERT INTO rate_limit_buckets
                (scope, bucket_key, window_started, event_count)
            VALUES (:scope, :key, :current, 1)
            ON CONFLICT(scope, bucket_key) DO UPDATE SET
                window_started = CASE
                    WHEN rate_limit_buckets.window_started <= :cutoff THEN :current
                    ELSE rate_limit_buckets.window_started
                END,
                event_count = CASE
                    WHEN rate_limit_buckets.window_started <= :cutoff THEN 1
                    ELSE rate_limit_buckets.event_count + 1
                END
            WHERE rate_limit_buckets.window_started <= :cutoff
               OR rate_limit_buckets.event_count < :limit
            RETURNING window_started
        """),
        {"scope": scope, "key": key[:128], "current": current, "cutoff": cutoff, "limit": limit},
    ).scalar_one_or_none()
    db.commit()
    if result is None:
        bucket = db.query(models.RateLimitBucket).filter(
            models.RateLimitBucket.scope == scope,
            models.RateLimitBucket.bucket_key == key[:128],
        ).first()
        retry_after = max(
            1,
            int(window_seconds - (current - bucket.window_started)) if bucket else window_seconds,
        )
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )


def _reject_if_window_full(
    buckets: dict, key, limit: int, detail: str, now: float | None = None
) -> None:
    """Read-only check of an in-memory window; never records an event."""
    current = time.monotonic() if now is None else now
    with _agent_rate_lock:
        events = buckets.get(key)
        while events and events[0] <= current - 60:
            events.popleft()
        if events and len(events) >= limit:
            raise HTTPException(
                status_code=429,
                detail=detail,
                headers={"Retry-After": str(max(1, int(60 - (current - events[0]))))},
            )


def _reject_if_shared_window_full(
    db: Session, scope: str, key: str, limit: int, detail: str,
    window_seconds: int = 60, now: float | None = None,
) -> None:
    """Read-only check of a shared window; never creates or increments a bucket."""
    current = time.time() if now is None else now
    bucket = db.query(models.RateLimitBucket).filter(
        models.RateLimitBucket.scope == scope,
        models.RateLimitBucket.bucket_key == key[:128],
    ).first()
    if (
        bucket is not None
        and bucket.window_started > current - window_seconds
        and bucket.event_count >= limit
    ):
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(
                max(1, int(window_seconds - (current - bucket.window_started)))
            )},
        )


def enforce_auth_rate_limit(request: Request, db: Session) -> None:
    # A client already over its own limit must not consume the shared global
    # budget; otherwise one address can lock every account out of login.
    client_key = _client_key(request)
    ip_detail = "驗證請求過於頻繁，請稍後再試。"
    _reject_if_window_full(_auth_rate_events, client_key, AUTH_RATE_LIMIT_PER_MINUTE, ip_detail)
    _reject_if_shared_window_full(db, "auth-ip", client_key, AUTH_RATE_LIMIT_PER_MINUTE, ip_detail)
    _enforce_shared_window_limit(
        db, "auth-global", "global", AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE,
        "驗證服務目前忙碌，請稍後再試。",
    )
    _enforce_window_limit(
        _auth_global_rate_events, "global", AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE,
        "驗證服務目前忙碌，請稍後再試。",
    )
    _enforce_window_limit(
        _auth_rate_events, client_key, AUTH_RATE_LIMIT_PER_MINUTE,
        "驗證請求過於頻繁，請稍後再試。",
    )
    _enforce_shared_window_limit(
        db, "auth-ip", client_key, AUTH_RATE_LIMIT_PER_MINUTE,
        "驗證請求過於頻繁，請稍後再試。",
    )


def enforce_agent_request_limits(request: Request, user_id: int, db: Session) -> None:
    # Reject a throttled network or account before it spends shared AI budget.
    client_key = _client_key(request)
    ip_detail = "此網路的 AI 請求過於頻繁，請稍後再試。"
    user_detail = "AI 請求過於頻繁，請稍後再試。"
    _reject_if_window_full(_agent_ip_rate_events, client_key, AGENT_IP_RATE_LIMIT_PER_MINUTE, ip_detail)
    _reject_if_window_full(_agent_rate_events, user_id, AGENT_RATE_LIMIT_PER_MINUTE, user_detail)
    _reject_if_shared_window_full(db, "agent-ip", client_key, AGENT_IP_RATE_LIMIT_PER_MINUTE, ip_detail)
    _reject_if_shared_window_full(db, "agent-user", str(user_id), AGENT_RATE_LIMIT_PER_MINUTE, user_detail)
    _enforce_shared_window_limit(
        db, "agent-global", "global", AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE,
        "AI 服務目前忙碌，請稍後再試。",
    )
    _enforce_window_limit(
        _agent_global_rate_events, "global", AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE,
        "AI 服務目前忙碌，請稍後再試。",
    )
    _enforce_window_limit(
        _agent_ip_rate_events, client_key, AGENT_IP_RATE_LIMIT_PER_MINUTE,
        "此網路的 AI 請求過於頻繁，請稍後再試。",
    )
    _enforce_agent_rate_limit(user_id)
    _enforce_shared_window_limit(
        db, "agent-ip", client_key, AGENT_IP_RATE_LIMIT_PER_MINUTE,
        "此網路的 AI 請求過於頻繁，請稍後再試。",
    )
    _enforce_shared_window_limit(
        db, "agent-user", str(user_id), AGENT_RATE_LIMIT_PER_MINUTE,
        "AI 請求過於頻繁，請稍後再試。",
    )


def enforce_model_refresh_limits(user_id: int, db: Session, now: float | None = None) -> None:
    """Apply account cooldown and shared/global refresh limits as one operation."""
    current = time.monotonic() if now is None else now
    with _agent_rate_lock:
        for stale_user_id, refreshed_at in list(_model_refresh_times.items()):
            if current - refreshed_at >= MODEL_REFRESH_COOLDOWN_SECONDS:
                _model_refresh_times.pop(stale_user_id, None)
        last_refresh = _model_refresh_times.get(user_id)
        if last_refresh is not None and current - last_refresh < MODEL_REFRESH_COOLDOWN_SECONDS:
            retry_after = max(1, int(MODEL_REFRESH_COOLDOWN_SECONDS - (current - last_refresh)))
            raise HTTPException(
                status_code=429,
                detail="模型列表剛更新過，請稍後再試。",
                headers={"Retry-After": str(retry_after)},
            )
        _model_refresh_times[user_id] = current
    try:
        _enforce_shared_window_limit(
            db, "model-refresh-global", "global", MODEL_REFRESH_GLOBAL_PER_MINUTE,
            "模型列表更新目前忙碌，請稍後再試。",
        )
        _enforce_window_limit(
            _model_refresh_global_events, "global", MODEL_REFRESH_GLOBAL_PER_MINUTE,
            "模型列表更新目前忙碌，請稍後再試。",
        )
    except Exception:
        with _agent_rate_lock:
            _model_refresh_times.pop(user_id, None)
        raise


# Private aliases retained for focused unit tests and gradual caller migration.
_enforce_auth_rate_limit = enforce_auth_rate_limit
_enforce_agent_request_limits = enforce_agent_request_limits


def _enforce_model_refresh_cooldown(user_id: int, now: float | None = None) -> None:
    """Compatibility helper that applies only the account cooldown."""
    current = time.monotonic() if now is None else now
    with _agent_rate_lock:
        for stale_user_id, refreshed_at in list(_model_refresh_times.items()):
            if current - refreshed_at >= MODEL_REFRESH_COOLDOWN_SECONDS:
                _model_refresh_times.pop(stale_user_id, None)
        last_refresh = _model_refresh_times.get(user_id)
        if last_refresh is not None and current - last_refresh < MODEL_REFRESH_COOLDOWN_SECONDS:
            retry_after = max(1, int(MODEL_REFRESH_COOLDOWN_SECONDS - (current - last_refresh)))
            raise HTTPException(
                status_code=429,
                detail="模型列表剛更新過，請稍後再試。",
                headers={"Retry-After": str(retry_after)},
            )
        _model_refresh_times[user_id] = current


# Failed password checks per username. The per-IP window alone still allows
# distributed guessing against one account; this bounds guesses per account.
LOGIN_FAILURE_LIMIT = 10
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_LOGIN_FAILURE_DETAIL = "此帳號登入失敗次數過多，請 15 分鐘後再試。"


def reject_locked_account(db: Session, username: str) -> None:
    _reject_if_shared_window_full(
        db, "auth-user-failure", username, LOGIN_FAILURE_LIMIT, _LOGIN_FAILURE_DETAIL,
        window_seconds=LOGIN_FAILURE_WINDOW_SECONDS,
    )


def record_login_failure(db: Session, username: str) -> None:
    try:
        _enforce_shared_window_limit(
            db, "auth-user-failure", username, LOGIN_FAILURE_LIMIT, _LOGIN_FAILURE_DETAIL,
            window_seconds=LOGIN_FAILURE_WINDOW_SECONDS,
        )
    except HTTPException:
        # Already at the limit; the next attempt is rejected by reject_locked_account.
        pass
