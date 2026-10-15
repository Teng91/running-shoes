import json
import os
import time
from calendar import monthrange
from collections import deque
from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from typing import Annotated, ClassVar, cast

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import Table, func, inspect, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend import agent, analytics, goals, llm, models, reports, schemas, strava_import
from backend.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from backend.database import Base, SessionLocal, engine, get_db
from backend.exporting import (
    export_filename as _get_export_filename,
)
from backend.exporting import (
    generate_shoe_rows as _generate_shoe_rows,
)

AGENT_RATE_LIMIT_PER_MINUTE = max(
    1, int(os.environ.get("AGENT_RATE_LIMIT_PER_MINUTE", "20"))
)
AGENT_IP_RATE_LIMIT_PER_MINUTE = max(
    1, int(os.environ.get("AGENT_IP_RATE_LIMIT_PER_MINUTE", "30"))
)
AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE = max(
    1, int(os.environ.get("AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE", "120"))
)
AUTH_RATE_LIMIT_PER_MINUTE = max(
    1, int(os.environ.get("AUTH_RATE_LIMIT_PER_MINUTE", "120"))
)
AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE = max(
    1, int(os.environ.get("AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE", "300"))
)
MAX_REGISTERED_USERS = max(1, int(os.environ.get("MAX_REGISTERED_USERS", "100")))
MAX_SHOES_PER_USER = max(1, int(os.environ.get("MAX_SHOES_PER_USER", "500")))
MAX_RUNS_PER_USER = max(1, int(os.environ.get("MAX_RUNS_PER_USER", "5000")))
MAX_STRAVA_CSV_BYTES = 10 * 1024 * 1024
MAX_STRAVA_REQUEST_BYTES = MAX_STRAVA_CSV_BYTES + 1024 * 1024
MAX_STRAVA_CSV_ROWS = 50_000
MAX_STRAVA_IMPORT_HISTORY_PER_USER = 50
MODEL_REFRESH_COOLDOWN_SECONDS = max(
    1, int(os.environ.get("MODEL_REFRESH_COOLDOWN_SECONDS", "60"))
)
MODEL_REFRESH_GLOBAL_PER_MINUTE = max(
    1, int(os.environ.get("MODEL_REFRESH_GLOBAL_PER_MINUTE", "10"))
)
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))
IS_FLY_RUNTIME = bool(os.environ.get("FLY_APP_NAME"))
_agent_rate_events: dict[int, deque[float]] = {}
_agent_ip_rate_events: dict[str, deque[float]] = {}
_agent_global_rate_events: dict[str, deque[float]] = {}
_auth_rate_events: dict[str, deque[float]] = {}
_auth_global_rate_events: dict[str, deque[float]] = {}
_model_refresh_times: dict[int, float] = {}
_model_refresh_global_events: dict[str, deque[float]] = {}
_agent_rate_lock = Lock()
_registration_lock = Lock()


class StravaUploadLimitMiddleware:
    """Reject oversized Strava multipart bodies before form parsing/spooling."""

    _paths: ClassVar[frozenset[str]] = frozenset({
        "/api/runs/import/strava",
        "/api/runs/import/strava/preview",
    })

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
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
                    {"detail": "Strava 上傳請求不可超過 11 MB"},
                    status_code=413,
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


def _enforce_agent_rate_limit(user_id: int, now: float | None = None) -> None:
    """Apply a small per-account sliding-window limit to server-key LLM calls."""
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


def _local_today() -> date:
    return datetime.now(TAIPEI_TIMEZONE).date()


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
        # Opportunistic cleanup prevents stale IP/account keys accumulating forever.
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
        {
            "scope": scope,
            "key": key[:128],
            "current": current,
            "cutoff": cutoff,
            "limit": limit,
        },
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


def _enforce_auth_rate_limit(request: Request, db: Session) -> None:
    _enforce_shared_window_limit(
        db, "auth-global", "global", AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE,
        "驗證服務目前忙碌，請稍後再試。",
    )
    _enforce_window_limit(
        _auth_global_rate_events,
        "global",
        AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE,
        "驗證服務目前忙碌，請稍後再試。",
    )
    _enforce_window_limit(
        _auth_rate_events,
        _client_key(request),
        AUTH_RATE_LIMIT_PER_MINUTE,
        "驗證請求過於頻繁，請稍後再試。",
    )
    _enforce_shared_window_limit(
        db, "auth-ip", _client_key(request), AUTH_RATE_LIMIT_PER_MINUTE,
        "驗證請求過於頻繁，請稍後再試。",
    )


def _enforce_agent_request_limits(request: Request, user_id: int, db: Session) -> None:
    _enforce_shared_window_limit(
        db, "agent-global", "global", AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE,
        "AI 服務目前忙碌，請稍後再試。",
    )
    _enforce_window_limit(
        _agent_global_rate_events,
        "global",
        AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE,
        "AI 服務目前忙碌，請稍後再試。",
    )
    _enforce_window_limit(
        _agent_ip_rate_events,
        _client_key(request),
        AGENT_IP_RATE_LIMIT_PER_MINUTE,
        "此網路的 AI 請求過於頻繁，請稍後再試。",
    )
    _enforce_agent_rate_limit(user_id)
    _enforce_shared_window_limit(
        db, "agent-ip", _client_key(request), AGENT_IP_RATE_LIMIT_PER_MINUTE,
        "此網路的 AI 請求過於頻繁，請稍後再試。",
    )
    _enforce_shared_window_limit(
        db, "agent-user", str(user_id), AGENT_RATE_LIMIT_PER_MINUTE,
        "AI 請求過於頻繁，請稍後再試。",
    )


def _enforce_model_refresh_cooldown(user_id: int, now: float | None = None) -> None:
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

# ── Seed default data (only when SEED_DATA=true) ──────────────
def seed_default_data():
    if os.environ.get("SEED_DATA", "").lower() != "true":
        return
    db = SessionLocal()
    try:
        # Ensure Joy exists (so seed data always belongs to her)
        joy_user = db.query(models.User).filter(models.User.username == "Joy").first()
        if not joy_user:
            migration_password = os.environ.get("MIGRATION_PASSWORD")
            if not migration_password:
                raise RuntimeError(
                    "MIGRATION_PASSWORD must be set when SEED_DATA=true so the "
                    "Joy account has a known password."
                )
            joy_user = models.User(username="Joy", hashed_password=get_password_hash(migration_password))
            db.add(joy_user)
            db.commit()
            db.refresh(joy_user)

        if db.query(models.Shoe).count() == 0:
            defaults = [
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Sky 7", date="2024-09-15", size="us13/31cm", price=2390, orig_price=4780, mileage=540, expected_mileage=800, monthly_km=60, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Rider 29", date="2025-12-12", size="us12/30cm", price=2505, orig_price=3980, mileage=293, expected_mileage=800, monthly_km=60, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Sky 9", date="2025-12-30", size="us13/31cm", price=3080, orig_price=4980, mileage=125, expected_mileage=800, monthly_km=60, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="New Balance", model="Rebel v5", date="2026-02-20", size="us11/29cm", price=2300, orig_price=4280, mileage=102, expected_mileage=500, monthly_km=30, categories=["Speed"]),
                models.Shoe(user_id=joy_user.id, brand="Adidas", model="Boston 12", date="2026-04-21", size="us11.5/29.5cm", price=1680, orig_price=4290, mileage=61, expected_mileage=800, monthly_km=30, categories=["Tempo"]),
                models.Shoe(user_id=joy_user.id, brand="PUMA", model="Nitro Elite 3", date="2026-06-25", size="us11.5/29.5cm", price=3310, orig_price=5980, mileage=0, expected_mileage=500, monthly_km=20, categories=["Race"]),
                models.Shoe(user_id=joy_user.id, brand="Asics", model="Gel-Excite 8", date="2024-01-05", size="us11/29cm", price=1780, orig_price=2280, mileage=625, expected_mileage=600, monthly_km=0, is_retired=True, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="FILA", model="Bon Voyage", date="2025-08-10", size="us11/29cm", price=2200, orig_price=2880, mileage=418, expected_mileage=400, monthly_km=0, is_retired=True, categories=["Daily"]),
            ]
            for shoe in defaults:
                shoe.baseline_mileage = shoe.mileage
            db.add_all(defaults)
            db.commit()

        if db.query(models.MonthlyMileage).filter(models.MonthlyMileage.user_id == joy_user.id).count() == 0:
            mileage_data = [
                (2023, 1, 2.91), (2023, 2, 2.87), (2023, 3, 29.42), (2023, 4, 56.65),
                (2023, 5, 41.05), (2023, 6, 6.67), (2023, 7, 6.05), (2023, 8, 4.04),
                (2023, 9, 11.67), (2023, 10, 23.34), (2023, 11, 12.08), (2023, 12, 0),
                (2024, 1, 0), (2024, 2, 8.27), (2024, 3, 3.96), (2024, 4, 6.38),
                (2024, 5, 4.3), (2024, 6, 3.48), (2024, 7, 0), (2024, 8, 70.11),
                (2024, 9, 53.21), (2024, 10, 37.43), (2024, 11, 47.91), (2024, 12, 17.42),
                (2025, 1, 0), (2025, 2, 23.15), (2025, 3, 56.34), (2025, 4, 32.7),
                (2025, 5, 50.64), (2025, 6, 43.39), (2025, 7, 79.2), (2025, 8, 81.07),
                (2025, 9, 51.97), (2025, 10, 67.49), (2025, 11, 102.49), (2025, 12, 196.32),
                (2026, 1, 125.71), (2026, 2, 135.91), (2026, 3, 130.13), (2026, 4, 78.41),
                (2026, 5, 149.12), (2026, 6, 128.2),
            ]
            entries = [
                models.MonthlyMileage(
                    user_id=joy_user.id, year=y, month=m, km=km, adjustment_km=km
                )
                for y, m, km in mileage_data
            ]
            db.add_all(entries)
            db.commit()
    finally:
        db.close()


# ── Lifespan: create tables & migrate ─────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # One-time migration: if old schema exists (shoes table without user_id), migrate
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    existing_shoe_columns = (
        {column["name"] for column in inspector.get_columns("shoes")}
        if "shoes" in existing_tables
        else set()
    )

    if "shoes" in existing_tables and "user_id" not in existing_shoe_columns:
        migration_password = os.environ.get("MIGRATION_PASSWORD")
        if not migration_password:
            raise RuntimeError(
                "MIGRATION_PASSWORD is required to migrate the legacy shoes database; "
                "refusing to start with an unusable schema."
            )

        # Old schema: create users table, add user_id to shoes, assign to "Joy"
        user_table = cast(Table, models.User.__table__)
        Base.metadata.create_all(bind=engine, tables=[user_table])
        with engine.begin() as conn:
            if "token_version" not in {c["name"] for c in inspect(conn).get_columns("users")}:
                conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
        db = SessionLocal()
        try:
            joy_user = db.query(models.User).filter(models.User.username == "Joy").first()
            if joy_user is None:
                joy_user = models.User(
                    username="Joy",
                    hashed_password=get_password_hash(migration_password),
                )
                db.add(joy_user)
                db.commit()
                db.refresh(joy_user)

            # Add user_id column (SQLite allows ALTER TABLE ADD COLUMN without FK)
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE shoes ADD COLUMN user_id INTEGER"))
                conn.execute(
                    text("UPDATE shoes SET user_id = :uid"),
                    {"uid": joy_user.id},
                )
                conn.commit()
        finally:
            db.close()

    Base.metadata.create_all(bind=engine)

    # Add concurrency/session versions to existing databases without changing data.
    for table, column in (
        ("users", "token_version"),
        ("shoes", "version"),
        ("shoes", "is_deleted"),
        ("runs", "version"),
        ("monthly_mileages", "version"),
        ("running_goals", "version"),
    ):
        columns = {item["name"] for item in inspect(engine).get_columns(table)}
        if column not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"))

    # Make historical/manual mileage explicit while preserving the exact totals
    # shown before this migration.  These baselines remain unchanged as runs are
    # added, edited, or deleted.
    shoe_columns = {column["name"] for column in inspect(engine).get_columns("shoes")}
    if "baseline_mileage" not in shoe_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE shoes ADD COLUMN baseline_mileage FLOAT NOT NULL DEFAULT 0"
            ))
            # Extremely old test/legacy tables may not yet have a mileage
            # column; their new baseline safely remains zero.
            if "mileage" in shoe_columns:
                conn.execute(text(
                    "UPDATE shoes SET baseline_mileage = mileage - COALESCE(("
                    "SELECT SUM(runs.km) FROM runs WHERE runs.shoe_id = shoes.id "
                    "AND runs.user_id = shoes.user_id), 0)"
                ))

    monthly_columns = {
        column["name"] for column in inspect(engine).get_columns("monthly_mileages")
    }
    if "adjustment_km" not in monthly_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE monthly_mileages "
                "ADD COLUMN adjustment_km FLOAT NOT NULL DEFAULT 0"
            ))
            conn.execute(text(
                "UPDATE monthly_mileages SET adjustment_km = km - COALESCE(("
                "SELECT SUM(runs.km) FROM runs WHERE runs.user_id = monthly_mileages.user_id "
                "AND CAST(substr(runs.date, 1, 4) AS INTEGER) = monthly_mileages.year "
                "AND CAST(substr(runs.date, 6, 2) AS INTEGER) = monthly_mileages.month), 0)"
            ))

    # Incremental migration for Strava provenance on run records.
    run_columns = {column["name"] for column in inspect(engine).get_columns("runs")}
    with engine.begin() as conn:
        if "strava_id" not in run_columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN strava_id VARCHAR"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_user_strava_id "
            "ON runs (user_id, strava_id) WHERE strava_id IS NOT NULL"
        ))

    # create_all() does not add indexes to tables that already exist.
    # Keep the run-log query path fast for upgraded databases as history grows.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_runs_user_date "
            "ON runs (user_id, date)"
        ))
        conn.execute(text("PRAGMA optimize"))

    # Incremental migration for SQLite databases created before shoe categories
    # were changed from a single string to a JSON array of multiple purposes.
    # create_all() does not alter existing tables, so we need ALTER TABLE here.
    shoe_columns = {column["name"] for column in inspect(engine).get_columns("shoes")}
    with engine.begin() as conn:
        if "categories" not in shoe_columns:
            if "category" in shoe_columns:
                # Legacy DB: migrate single-string category → JSON array, then drop old column
                conn.execute(text("ALTER TABLE shoes ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'"))
                conn.execute(text("UPDATE shoes SET categories = json_array(category) WHERE category IS NOT NULL AND category != ''"))
                conn.execute(text("ALTER TABLE shoes DROP COLUMN category"))
            else:
                # Table exists but has no category column at all — add the new one
                conn.execute(text("ALTER TABLE shoes ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'"))
        # Remove discontinued categories in one pass, including repeated values.
        # Preserve the remaining labels and leave shoes with no remaining purpose unclassified.
        conn.execute(text("""
            UPDATE shoes
            SET categories = (
                SELECT json_group_array(value) FROM json_each(shoes.categories)
                WHERE value NOT IN ('Other', 'Walk', 'Trail')
            ), version = version + 1
            WHERE EXISTS (
                SELECT 1 FROM json_each(shoes.categories)
                WHERE value IN ('Other', 'Walk', 'Trail')
            )
        """))

    seed_default_data()
    yield


app = FastAPI(title="Running Shoes API", lifespan=lifespan)

app.add_middleware(StravaUploadLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve static frontend ─────────────────────────────────────
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
frontend_dir.mkdir(exist_ok=True)


# index.html 內含 inline JS，必須用 no-cache 讓瀏覽器每次都向伺服器
# 驗證（FileResponse 內建 ETag/Last-Modified，未變更會回 304 很省），
# 否則使用者會一直卡在舊版前端。
def _index_response():
    return FileResponse(
        frontend_dir / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    """Return index.html for 404s so SPA-style routing works,
    but return proper JSON for API errors (4xx/5xx)."""
    if exc.status_code == 404:
        path = request.url.path
        if path.startswith(("/api/", "/docs", "/openapi.json")):
            return JSONResponse(
                {"detail": exc.detail},
                status_code=404,
                headers=exc.headers,
            )
        # Resolve and ensure the file lives inside frontend_dir — otherwise
        # a path like "/../shoes.db" could escape and serve arbitrary files.
        try:
            candidate = (frontend_dir / path.lstrip("/")).resolve()
        except (OSError, ValueError):
            return _index_response()
        if frontend_dir.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return _index_response()
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


# ── Auth Routes ───────────────────────────────────────────────
@app.post("/api/auth/register", response_model=schemas.UserOut)
def register(request: Request, payload: schemas.UserCreate, db: Session = Depends(get_db)):
    _enforce_auth_rate_limit(request, db)
    if len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    if len(username) > 50:
        raise HTTPException(status_code=400, detail="Username must be 50 characters or fewer")
    with _registration_lock:
        if db.query(models.User).filter(models.User.username == username).first():
            raise HTTPException(status_code=400, detail="Username already registered")
        if db.query(models.User).count() >= MAX_REGISTERED_USERS:
            raise HTTPException(status_code=403, detail="Registration capacity has been reached")
        user = models.User(
            username=username,
            hashed_password=get_password_hash(payload.password),
        )
        db.add(user)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(user)
    return user


@app.post("/api/auth/login", response_model=schemas.Token)
def login(request: Request, payload: schemas.UserLogin, db: Session = Depends(get_db)):
    _enforce_auth_rate_limit(request, db)
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_access_token(data={"sub": user.username, "token_version": user.token_version})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/auth/me", response_model=schemas.UserOut)
def read_current_user(current_user: models.User = Depends(get_current_user)):
    return current_user


@app.post("/api/auth/change-password")
def change_password(
    request: Request,
    payload: schemas.UserChangePassword,
    db: Session = Depends(get_db),
):
    _enforce_auth_rate_limit(request, db)
    if len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or old password")
    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or old password")
    user.token_version += 1
    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"ok": True}


# ── Shoe Routes ───────────────────────────────────────────────


@app.get("/api/shoes/active", response_model=list[schemas.ShoeOut])
def list_active(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Shoe).filter(
        models.Shoe.is_retired.is_(False),
        models.Shoe.is_deleted.is_(False),
        models.Shoe.user_id == current_user.id,
    ).all()


@app.get("/api/shoes/retired", response_model=list[schemas.ShoeOut])
def list_retired(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Shoe).filter(
        models.Shoe.is_retired.is_(True),
        models.Shoe.is_deleted.is_(False),
        models.Shoe.user_id == current_user.id,
    ).all()


@app.post("/api/shoes", response_model=schemas.ShoeOut)
def create_shoe(
    payload: schemas.ShoeCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe_count = db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).count()
    if isinstance(shoe_count, int) and shoe_count >= MAX_SHOES_PER_USER:
        raise HTTPException(status_code=409, detail="跑鞋資料已達上限")
    shoe = models.Shoe(
        **payload.model_dump(),
        baseline_mileage=payload.mileage,
        user_id=current_user.id,
    )
    db.add(shoe)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(shoe)
    return shoe


@app.put("/api/shoes/{shoe_id}", response_model=schemas.ShoeOut)
def update_shoe(
    shoe_id: int,
    payload: schemas.ShoeUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    update_data = payload.model_dump(exclude_unset=True)
    supplied_version = update_data.pop("expected_version", None)
    current_version = int(getattr(shoe, "version", 0))
    if supplied_version is not None and supplied_version != current_version:
        raise HTTPException(status_code=409, detail="鞋款已被更新，請重新載入後再編輯")
    expected_version = current_version
    if "mileage" in update_data:
        logged_mileage = db.query(func.sum(models.Run.km)).filter(
            models.Run.user_id == current_user.id,
            models.Run.shoe_id == shoe_id,
        ).scalar()
        logged_total = round(float(logged_mileage or 0), 2)
        if float(update_data["mileage"]) + 0.005 < logged_total:
            raise HTTPException(
                status_code=400,
                detail=f"總里程不可低於逐筆跑步日誌合計 {logged_total:.2f} km",
            )
        update_data["baseline_mileage"] = round(
            float(update_data["mileage"]) - logged_total, 2
        )
    query = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id, models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    )
    query = query.filter(models.Shoe.version == expected_version)
    try:
        update_data["version"] = models.Shoe.version + 1
        changed = query.update(
            {getattr(models.Shoe, key): value for key, value in update_data.items()},
            synchronize_session=False,
        )
        if not changed:
            raise HTTPException(status_code=409, detail="鞋款已被更新，請重新載入後再編輯")
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(shoe)
    return shoe


@app.delete("/api/shoes/{shoe_id}")
def delete_shoe(
    shoe_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    version = getattr(shoe, "version", 0) if expected_version is None else expected_version
    try:
        changed = db.query(models.Shoe).filter(
            models.Shoe.id == shoe_id,
            models.Shoe.user_id == current_user.id,
            models.Shoe.is_deleted.is_(False),
            models.Shoe.version == version,
        ).update(
            {
                models.Shoe.is_deleted: True,
                models.Shoe.version: models.Shoe.version + 1,
            },
            synchronize_session=False,
        )
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="鞋款已被更新，請重新載入後再刪除",
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}


# ── Run Log Routes ──
def _user_shoe_or_404(db: Session, user_id: int, shoe_id: int) -> models.Shoe:
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    return shoe


def _apply_run_mileage_deltas(
    db: Session,
    user_id: int,
    run_values: Sequence[tuple[int, str, float]],
    multiplier: int,
) -> float:
    """Apply run deltas to shoe totals and monthly mileage in one transaction."""
    shoe_deltas: dict[int, float] = {}
    month_deltas: dict[tuple[int, int], float] = {}
    total_delta = 0.0
    for shoe_id, run_date, km in run_values:
        delta = round(km * multiplier, 2)
        shoe_deltas[shoe_id] = shoe_deltas.get(shoe_id, 0.0) + delta
        year, month = int(run_date[:4]), int(run_date[5:7])
        month_deltas[(year, month)] = month_deltas.get((year, month), 0.0) + delta
        total_delta += delta

    for shoe_id, delta in shoe_deltas.items():
        if abs(delta) < 0.005:
            continue
        db.query(models.Shoe).filter(
            models.Shoe.id == shoe_id,
            models.Shoe.user_id == user_id,
        ).update(
            {
                models.Shoe.version: models.Shoe.version + 1,
                models.Shoe.mileage: func.max(
                    0,
                    func.coalesce(models.Shoe.mileage, 0) + round(delta, 2),
                )
            },
            synchronize_session=False,
        )

    for (year, month), delta in month_deltas.items():
        if abs(delta) < 0.005:
            continue
        rounded_delta = round(delta, 2)
        if rounded_delta > 0:
            # A single SQLite upsert avoids a query-then-insert race when two
            # runs create the first aggregate row for the same month.
            statement = sqlite_insert(models.MonthlyMileage).values(
                user_id=user_id,
                year=year,
                month=month,
                km=rounded_delta,
                adjustment_km=0,
                version=0,
            )
            statement = statement.on_conflict_do_update(
                index_elements=["user_id", "year", "month"],
                set_={
                    "km": func.max(
                        0,
                        func.coalesce(models.MonthlyMileage.km, 0)
                        + rounded_delta,
                    ),
                    "version": models.MonthlyMileage.version + 1,
                },
            )
            db.execute(statement)
        else:
            db.query(models.MonthlyMileage).filter(
                models.MonthlyMileage.user_id == user_id,
                models.MonthlyMileage.year == year,
                models.MonthlyMileage.month == month,
            ).update(
                {
                    models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
                    models.MonthlyMileage.km: func.max(
                        0,
                        func.coalesce(models.MonthlyMileage.km, 0)
                        + rounded_delta,
                    )
                },
                synchronize_session=False,
            )
    return round(total_delta, 2)


def _parse_strava_csv(raw: bytes) -> tuple[list[dict[str, object]], int, list[str]]:
    return strava_import.parse_csv(raw, max_rows=MAX_STRAVA_CSV_ROWS)


def _filter_strava_rows(
    rows: list[dict[str, object]], start_date: str, end_date: str
) -> tuple[list[dict[str, object]], int]:
    return strava_import.filter_rows(rows, start_date, end_date)


async def _read_strava_upload(file: UploadFile) -> bytes:
    raw = await file.read(MAX_STRAVA_CSV_BYTES + 1)
    if len(raw) > MAX_STRAVA_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV 檔案不可超過 10 MB")
    return raw


def _strava_preview(
    db: Session,
    user_id: int,
    rows: list[dict[str, object]],
    invalid: int,
    warnings: list[str],
) -> dict[str, object]:
    return strava_import.build_preview(db, user_id, rows, invalid, warnings)


@app.post("/api/runs/import/strava/preview")
async def preview_strava_import(
    file: UploadFile = File(...),
    start_date: str = Form(""),
    end_date: str = Form(""),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = await _read_strava_upload(file)
    rows, invalid, warnings = _parse_strava_csv(raw)
    rows, filtered_out = _filter_strava_rows(rows, start_date, end_date)
    preview = _strava_preview(db, current_user.id, rows, invalid, warnings)
    preview["filtered_out"] = filtered_out
    return preview


@app.post("/api/runs/import/strava")
async def import_strava_runs(
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        parsed_mapping = json.loads(mapping)
        if not isinstance(parsed_mapping, dict):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="鞋款配對格式錯誤") from exc
    raw = await _read_strava_upload(file)
    rows, invalid, _ = _parse_strava_csv(raw)
    rows, filtered_out = _filter_strava_rows(rows, start_date, end_date)
    shoes = {shoe.id: shoe for shoe in db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).all()}
    normalized_mapping: dict[str, int | None] = {}
    for gear, shoe_id in parsed_mapping.items():
        if shoe_id in (None, "", 0, "0"):
            normalized_mapping[str(gear)] = None
            continue
        try:
            shoe_id_int = int(cast(str | int, shoe_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="鞋款配對格式錯誤") from exc
        if shoe_id_int not in shoes:
            raise HTTPException(status_code=404, detail="鞋款不存在或不屬於目前帳號")
        normalized_mapping[str(gear)] = shoe_id_int
    existing_ids = {
        value[0] for value in db.query(models.Run.strava_id).filter(
            models.Run.user_id == current_user.id, models.Run.strava_id.isnot(None)
        ).all()
    }
    seen: set[str] = set()
    runs_to_add: list[models.Run] = []
    skipped_duplicate = 0
    skipped_unmapped = 0
    for row in rows:
        strava_id = str(row["strava_id"])
        if strava_id in existing_ids or strava_id in seen:
            skipped_duplicate += 1
            continue
        seen.add(strava_id)
        shoe_id = normalized_mapping.get(str(row["gear"]))
        if shoe_id is None:
            skipped_unmapped += 1
            continue
        runs_to_add.append(models.Run(
            user_id=current_user.id,
            shoe_id=shoe_id,
            date=str(row["date"]),
            km=float(cast(float, row["km"])),
            strava_id=strava_id,
        ))
    current_count = db.query(models.Run).filter(models.Run.user_id == current_user.id).count()
    if current_count + len(runs_to_add) > MAX_RUNS_PER_USER:
        raise HTTPException(status_code=409, detail="匯入後跑步紀錄將超過上限")
    synced_mileage = _apply_run_mileage_deltas(
        db,
        current_user.id,
        [(run.shoe_id, run.date, run.km) for run in runs_to_add],
        1,
    )
    db.add_all(runs_to_add)
    import_record = models.StravaImport(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        imported_count=len(runs_to_add),
        imported_km=synced_mileage,
        duplicate_count=skipped_duplicate,
        unmapped_count=skipped_unmapped,
        invalid_count=invalid,
    )
    db.add(import_record)
    try:
        db.flush()
        stale_import_ids = [
            value[0] for value in db.query(models.StravaImport.id).filter(
                models.StravaImport.user_id == current_user.id,
            ).order_by(
                models.StravaImport.imported_at.desc(),
                models.StravaImport.id.desc(),
            ).offset(MAX_STRAVA_IMPORT_HISTORY_PER_USER).all()
        ]
        if stale_import_ids:
            db.query(models.StravaImport).filter(
                models.StravaImport.user_id == current_user.id,
                models.StravaImport.id.in_(stale_import_ids),
            ).delete(synchronize_session=False)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="部分 Strava 活動已存在，請重新預覽") from exc
    except Exception:
        db.rollback()
        raise
    return {
        "imported": len(runs_to_add),
        "skipped_duplicate": skipped_duplicate,
        "skipped_unmapped": skipped_unmapped,
        "skipped_invalid": invalid,
        "filtered_out": filtered_out,
        "synced_mileage": round(synced_mileage, 2),
        "total_run_rows": len(rows),
    }


@app.get("/api/runs/import/strava/history", response_model=list[schemas.StravaImportOut])
def list_strava_imports(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.StravaImport).filter(
        models.StravaImport.user_id == current_user.id,
    ).order_by(models.StravaImport.imported_at.desc(), models.StravaImport.id.desc()).limit(10).all()


@app.get("/api/runs", response_model=list[schemas.RunOut])
def list_runs(
    year: int | None = Query(default=None, ge=1900, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail="month requires year")
    query = db.query(models.Run).filter(models.Run.user_id == current_user.id)
    if year is not None:
        if month is None:
            start_date = f"{year:04d}-01-01"
            end_date = f"{year:04d}-12-31"
        else:
            last_day = monthrange(year, month)[1]
            start_date = f"{year:04d}-{month:02d}-01"
            end_date = f"{year:04d}-{month:02d}-{last_day:02d}"
        query = query.filter(
            models.Run.date >= start_date,
            models.Run.date <= end_date,
        )
    query = query.order_by(models.Run.date.desc(), models.Run.id.desc()).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


@app.post("/api/runs", response_model=schemas.RunOut)
def create_run(
    payload: schemas.RunCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _user_shoe_or_404(db, current_user.id, payload.shoe_id)
    run_count = db.query(models.Run).filter(models.Run.user_id == current_user.id).count()
    if isinstance(run_count, int) and run_count >= MAX_RUNS_PER_USER:
        raise HTTPException(status_code=409, detail="跑步紀錄已達上限")
    run = models.Run(**payload.model_dump(), user_id=current_user.id)
    db.add(run)
    try:
        _apply_run_mileage_deltas(
            db,
            current_user.id,
            [(payload.shoe_id, payload.date, payload.km)],
            1,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run


@app.put("/api/runs/{run_id}", response_model=schemas.RunOut)
def update_run(
    run_id: int,
    payload: schemas.RunUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(models.Run).filter(
        models.Run.id == run_id,
        models.Run.user_id == current_user.id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    update_data = payload.model_dump(exclude_unset=True)
    expected_version = update_data.pop("expected_version", getattr(run, "version", 0))
    if "shoe_id" in update_data:
        _user_shoe_or_404(db, current_user.id, update_data["shoe_id"])
    old_values = (run.shoe_id, run.date, run.km)
    new_values = (
        int(update_data.get("shoe_id", run.shoe_id)),
        str(update_data.get("date", run.date)),
        float(update_data.get("km", run.km)),
    )
    try:
        changed = db.query(models.Run).filter(
            models.Run.id == run_id,
            models.Run.user_id == current_user.id,
            models.Run.version == expected_version,
        ).update(
            {
                **{
                    getattr(models.Run, key): value
                    for key, value in update_data.items()
                },
                models.Run.version: models.Run.version + 1,
            },
            synchronize_session=False,
        )
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="跑步紀錄已被更新，請重新載入後再編輯",
            )
        _apply_run_mileage_deltas(
            db,
            current_user.id,
            [
                (old_values[0], old_values[1], -old_values[2]),
                new_values,
            ],
            1,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run


@app.delete("/api/runs/{run_id}")
def delete_run(
    run_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(models.Run).filter(
        models.Run.id == run_id,
        models.Run.user_id == current_user.id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run_values = (run.shoe_id, run.date, run.km)
    version = getattr(run, "version", 0) if expected_version is None else expected_version
    try:
        changed = db.query(models.Run).filter(
            models.Run.id == run_id,
            models.Run.user_id == current_user.id,
            models.Run.version == version,
        ).delete(synchronize_session=False)
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="跑步紀錄已被更新，請重新載入後再刪除",
            )
        _apply_run_mileage_deltas(db, current_user.id, [run_values], -1)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}


# ── Monthly Mileage Routes ──
@app.get("/api/running-goal", response_model=schemas.RunningGoalOut)
def get_running_goal(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return goals.goal_values(db, current_user.id)


@app.put("/api/running-goal", response_model=schemas.RunningGoalOut)
def update_running_goal(
    payload: schemas.RunningGoalUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload_data = payload.model_dump()
    expected_version = payload_data.pop("expected_version", None)
    if expected_version is None:
        current_version = db.query(models.RunningGoal.version).filter(
            models.RunningGoal.user_id == current_user.id
        ).scalar()
        expected_version = int(current_version or 0)
    insert_statement = sqlite_insert(models.RunningGoal).values(
        user_id=current_user.id,
        version=1,
        start_year=payload.start_year,
        monthly_km=payload.monthly_km,
        yearly_km=payload.monthly_km * 12,
    )
    statement = insert_statement.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "start_year": payload.start_year,
            "monthly_km": payload.monthly_km,
            "yearly_km": payload.monthly_km * 12,
            "version": models.RunningGoal.version + 1,
        },
        where=models.RunningGoal.version == expected_version,
    ).returning(models.RunningGoal.id)
    try:
        changed_id = db.execute(statement).scalar_one_or_none()
        if changed_id is None:
            raise HTTPException(
                status_code=409,
                detail="跑量目標已被更新，請重新載入後再編輯",
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return goals.goal_values(db, current_user.id)


@app.get("/api/monthly-mileage", response_model=list[schemas.MonthlyMileageOut])
def list_monthly_mileage(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == current_user.id,
    ).order_by(models.MonthlyMileage.year, models.MonthlyMileage.month).all()
    return rows


@app.post("/api/monthly-mileage", response_model=schemas.MonthlyMileageOut)
def create_monthly_mileage(
    payload: schemas.MonthlyMileageCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == current_user.id,
        models.MonthlyMileage.year == payload.year,
        models.MonthlyMileage.month == payload.month,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="該月份已有紀錄")

    logged_km = db.query(func.sum(models.Run.km)).filter(
        models.Run.user_id == current_user.id,
        models.Run.date.like(f"{payload.year:04d}-{payload.month:02d}-%"),
    ).scalar()
    logged_total = round(float(logged_km or 0), 2)
    if payload.km + 0.005 < logged_total:
        raise HTTPException(
            status_code=400,
            detail=f"月跑量不可低於逐筆跑步日誌合計 {logged_total:.2f} km",
        )
    entry = models.MonthlyMileage(
        **payload.model_dump(),
        adjustment_km=round(payload.km - logged_total, 2),
        user_id=current_user.id,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="該月份已有紀錄") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


@app.put("/api/monthly-mileage/{entry_id}", response_model=schemas.MonthlyMileageOut)
def update_monthly_mileage(
    entry_id: int,
    payload: schemas.MonthlyMileageUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.id == entry_id,
        models.MonthlyMileage.user_id == current_user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Monthly mileage not found")

    update_data = payload.model_dump(exclude_unset=True)
    expected_version = update_data.pop(
        "expected_version", getattr(entry, "version", 0)
    )
    new_month = update_data.get("month", entry.month)
    new_year = update_data.get("year", entry.year)

    # Check uniqueness if year/month are changing
    if ("year" in update_data or "month" in update_data) and (
        new_year != entry.year or new_month != entry.month
    ):
        source_logged_km = db.query(func.sum(models.Run.km)).filter(
            models.Run.user_id == current_user.id,
            models.Run.date.like(f"{entry.year:04d}-{entry.month:02d}-%"),
        ).scalar()
        if float(source_logged_km or 0) > 0.005:
            raise HTTPException(
                status_code=400,
                detail="此月份已有逐筆跑步日誌，請先修改跑步日期，不能直接移動月份",
            )
        clash = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.user_id == current_user.id,
            models.MonthlyMileage.year == new_year,
            models.MonthlyMileage.month == new_month,
            models.MonthlyMileage.id != entry_id,
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="該月份已有紀錄")

    # A manually entered total is represented as an adjustment alongside the
    # immutable sum of detailed run-log rows for that target month.
    desired_total = float(update_data.get("km", entry.km))
    logged_km = db.query(func.sum(models.Run.km)).filter(
        models.Run.user_id == current_user.id,
        models.Run.date.like(f"{new_year:04d}-{new_month:02d}-%"),
    ).scalar()
    logged_total = round(float(logged_km or 0), 2)
    if desired_total + 0.005 < logged_total:
        raise HTTPException(
            status_code=400,
            detail=f"月跑量不可低於逐筆跑步日誌合計 {logged_total:.2f} km",
        )
    update_data["adjustment_km"] = round(desired_total - logged_total, 2)
    try:
        changed = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.id == entry_id,
            models.MonthlyMileage.user_id == current_user.id,
            models.MonthlyMileage.version == expected_version,
        ).update(
            {
                **{
                    getattr(models.MonthlyMileage, key): value
                    for key, value in update_data.items()
                },
                models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
            },
            synchronize_session=False,
        )
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="月跑量已被更新，請重新載入後再編輯",
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="該月份已有紀錄") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


@app.delete("/api/monthly-mileage/{entry_id}")
def delete_monthly_mileage(
    entry_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.id == entry_id,
        models.MonthlyMileage.user_id == current_user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Monthly mileage not found")
    version = getattr(entry, "version", 0) if expected_version is None else expected_version
    logged_km = db.query(func.sum(models.Run.km)).filter(
        models.Run.user_id == current_user.id,
        models.Run.date.like(f"{entry.year:04d}-{entry.month:02d}-%"),
    ).scalar()
    try:
        if logged_km:
            # Detailed runs are the source of truth.  "Delete" removes only the
            # historical/manual adjustment when run-log rows still exist.
            changed = db.query(models.MonthlyMileage).filter(
                models.MonthlyMileage.id == entry_id,
                models.MonthlyMileage.user_id == current_user.id,
                models.MonthlyMileage.version == version,
            ).update(
                {
                    models.MonthlyMileage.adjustment_km: 0,
                    models.MonthlyMileage.km: round(float(logged_km), 2),
                    models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
                },
                synchronize_session=False,
            )
        else:
            changed = db.query(models.MonthlyMileage).filter(
                models.MonthlyMileage.id == entry_id,
                models.MonthlyMileage.user_id == current_user.id,
                models.MonthlyMileage.version == version,
            ).delete(synchronize_session=False)
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="月跑量已被更新，請重新載入後再刪除",
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}


# ── Export Routes ─────────────────────────────────────────────────
@app.get("/api/analytics/dashboard")
def dashboard_analytics(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return analytics.dashboard_analytics(db, current_user.id, year, month)


@app.get("/api/shoes/{shoe_id}/analytics")
def get_shoe_analytics(
    shoe_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = analytics.shoe_analytics(db, current_user.id, shoe_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Shoe not found")
    return result


@app.get("/api/export/account")
def export_account_data(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export all user-owned product records without credentials or secrets."""
    shoes = db.query(models.Shoe).filter(models.Shoe.user_id == current_user.id).all()
    runs = db.query(models.Run).filter(models.Run.user_id == current_user.id).all()
    months = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == current_user.id
    ).all()
    report_rows = db.query(models.MonthlyReport).filter(
        models.MonthlyReport.user_id == current_user.id
    ).all()
    imports = db.query(models.StravaImport).filter(
        models.StravaImport.user_id == current_user.id
    ).all()
    goal = db.query(models.RunningGoal).filter(
        models.RunningGoal.user_id == current_user.id
    ).first()
    payload = {
        "format": "running-shoes-account-backup",
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "username": current_user.username,
        "shoes": [{
            "id": shoe.id, "brand": shoe.brand, "model": shoe.model,
            "date": shoe.date, "size": shoe.size, "price": shoe.price,
            "orig_price": shoe.orig_price, "mileage": shoe.mileage,
            "baseline_mileage": shoe.baseline_mileage,
            "expected_mileage": shoe.expected_mileage, "monthly_km": shoe.monthly_km,
            "is_retired": shoe.is_retired, "is_deleted": shoe.is_deleted,
            "categories": shoe.categories,
        } for shoe in shoes],
        "runs": [{
            "id": run.id, "shoe_id": run.shoe_id, "date": run.date, "km": run.km,
            "strava_id": run.strava_id,
        } for run in runs],
        "monthly_mileages": [{
            "year": row.year, "month": row.month, "km": row.km,
            "adjustment_km": row.adjustment_km,
        } for row in months],
        "running_goal": ({
            "start_year": goal.start_year, "monthly_km": goal.monthly_km,
            "yearly_km": goal.yearly_km,
        } if goal else None),
        "monthly_reports": [{
            "year": row.year, "month": row.month, "content_md": row.content_md,
            "model": row.model, "stats_json": row.stats_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        } for row in report_rows],
        "strava_imports": [{
            "imported_at": row.imported_at.isoformat() if row.imported_at else None,
            "start_date": row.start_date, "end_date": row.end_date,
            "imported_count": row.imported_count, "imported_km": row.imported_km,
            "duplicate_count": row.duplicate_count, "unmapped_count": row.unmapped_count,
            "invalid_count": row.invalid_count,
        } for row in imports],
    }
    filename = f"running_shoes_account_{datetime.now().astimezone():%Y%m%d_%H%M%S}.json"
    return JSONResponse(
        payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export")
def export_shoes(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    mode: str = Query("active", pattern="^(all|active|retired)$"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """匯出跑鞋資料為 CSV 或 XLSX。

    - format: csv 或 xlsx (預設 xlsx)
    - mode: all(全部) | active(現役) | retired(退役) (預設 active)
    """
    # 查詢鞋款
    query = db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    )
    if mode == "active":
        query = query.filter(models.Shoe.is_retired == False)  # noqa: E712
    elif mode == "retired":
        query = query.filter(models.Shoe.is_retired == True)  # noqa: E712
    # mode == "all" 不加額外過濾
    shoes = query.order_by(models.Shoe.is_retired, models.Shoe.date.desc()).all()

    if not shoes:
        raise HTTPException(status_code=404, detail="沒有可匯出的跑鞋資料")

    include_status = mode != "retired"  # 退役模式不需要狀態欄（全是已退役）
    rows = list(_generate_shoe_rows(shoes, include_retired_status=include_status))

    if format == "csv":
        # 生成 CSV
        import csv
        import io
        csv_output = io.StringIO()
        if rows:
            writer = csv.DictWriter(csv_output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        return StreamingResponse(
            io.BytesIO(csv_output.getvalue().encode("utf-8-sig")),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{_get_export_filename("csv", mode)}"'
            },
        )

    elif format == "xlsx":
        # 生成 XLSX (需要 openpyxl)
        import io
        try:
            import openpyxl
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail="伺服器缺少 openpyxl 套件，無法匯出 XLSX",
            ) from exc

        wb = openpyxl.Workbook()
        ws = wb.active
        if ws is None:
            raise RuntimeError("openpyxl did not create an active worksheet")
        ws.title = "跑鞋資料"

        if rows:
            headers = list(rows[0].keys())
            # 寫入標題列
            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
            header_alignment = Alignment(horizontal="center")

            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment

            # 寫入資料列
            for row_idx, row in enumerate(rows, 2):
                for col_idx, header in enumerate(headers, 1):
                    ws.cell(row=row_idx, column=col_idx, value=row[header])

            # 自動調整欄寬
            for col_idx in range(1, len(headers) + 1):
                ws.column_dimensions[get_column_letter(col_idx)].width = 18

        xlsx_output = io.BytesIO()
        wb.save(xlsx_output)
        xlsx_output.seek(0)

        return StreamingResponse(
            xlsx_output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{_get_export_filename("xlsx", mode)}"'
            },
        )


# ── Spending Routes ────────────────────────────────────────────
@app.get("/api/spending/monthly")
def monthly_spending(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回傳每月鞋款支出統計（依購買日期 grouped）。"""
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).all()

    buckets: dict[tuple[int, int], dict] = {}
    for s in shoes:
        if not s.date:
            continue
        try:
            year = int(s.date[:4])
            month = int(s.date[5:7])
        except (ValueError, IndexError):
            continue
        key = (year, month)
        if key not in buckets:
            buckets[key] = {"year": year, "month": month, "total_paid": 0.0, "total_orig": 0.0}
        buckets[key]["total_paid"] += s.price
        buckets[key]["total_orig"] += s.orig_price or 0

    result = sorted(buckets.values(), key=lambda x: (x["year"], x["month"]))
    return result


# ── Agent / Chat Routes ────────────────────────────────────────
@app.get("/api/agent/providers")
def list_agent_providers(
    current_user: models.User = Depends(get_current_user),
):
    """回傳 provider/model 清單（含 key 是否已設定）。"""
    return llm.list_providers()


@app.post("/api/agent/models/refresh")
def refresh_agent_models(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """強制刷新 OpenRouter 免費模型快取，回傳更新後的 provider/model 清單。"""
    _enforce_model_refresh_cooldown(current_user.id)
    try:
        _enforce_shared_window_limit(
            db,
            "model-refresh-global",
            "global",
            MODEL_REFRESH_GLOBAL_PER_MINUTE,
            "模型列表更新目前忙碌，請稍後再試。",
        )
        _enforce_window_limit(
            _model_refresh_global_events,
            "global",
            MODEL_REFRESH_GLOBAL_PER_MINUTE,
            "模型列表更新目前忙碌，請稍後再試。",
        )
    except Exception:
        # A rejected global attempt did not refresh anything and must not leave
        # this account in cooldown.
        with _agent_rate_lock:
            _model_refresh_times.pop(current_user.id, None)
        raise
    return llm.list_providers(force=True)


@app.post("/api/agent/chat/stream")
def agent_chat_stream(
    request: Request,
    payload: schemas.AgentChatRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 串流版：與 /api/agent/chat 相同，但 LLM token 會逐字即時送達。"""
    _enforce_agent_request_limits(request, current_user.id, db)
    try:
        provider = llm.LLMProvider.from_str(payload.provider)
        model = llm.resolve_allowed_model(provider, payload.model)
    except llm.LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        agent.run_agent_stream(
            user_message=payload.user_message,
            history=[turn.model_dump() for turn in payload.history],
            provider=provider.value,
            model=model,
            db=db,
            user_id=current_user.id,
        ),
        media_type="text/event-stream",
    )


# ── 月度跑步報告 Routes ────────────────────────────────────────
@app.post("/api/reports/generate")
def generate_monthly_report(
    request: Request,
    payload: schemas.ReportGenerateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """以 one-shot LLM 串流產生指定月份的跑步報告，成功後存入資料庫。"""
    _enforce_agent_request_limits(request, current_user.id, db)
    today = _local_today()
    if (payload.year, payload.month) > (today.year, today.month):
        raise HTTPException(status_code=422, detail="未來月份無法產生報告")
    try:
        model = llm.resolve_allowed_model(llm.LLMProvider.openrouter, payload.model)
    except llm.LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        reports.generate_report_stream(
            db,
            current_user.id,
            payload.year,
            payload.month,
            model,
            today=today,
        ),
        media_type="text/event-stream",
    )


@app.get("/api/reports")
def list_monthly_reports(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出目前帳號所有已儲存的月度報告（不含報告內文）。"""
    rows = (
        db.query(models.MonthlyReport)
        .filter(models.MonthlyReport.user_id == current_user.id)
        .order_by(models.MonthlyReport.year.desc(), models.MonthlyReport.month.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "year": row.year,
            "month": row.month,
            "model": row.model,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@app.get("/api/reports/{year}/{month}")
def get_monthly_report(
    year: int,
    month: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取得指定月份的完整月度報告；不存在時回 404。"""
    row = (
        db.query(models.MonthlyReport)
        .filter(
            models.MonthlyReport.user_id == current_user.id,
            models.MonthlyReport.year == year,
            models.MonthlyReport.month == month,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="查無此月份的報告")
    return {
        "id": row.id,
        "year": row.year,
        "month": row.month,
        "model": row.model,
        "content_md": row.content_md,
        "stats_json": row.stats_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
