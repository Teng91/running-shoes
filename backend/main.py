import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from typing import Annotated, ClassVar

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend import agent, goals, llm, migrations, models, reports, schemas
from backend.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from backend.database import SessionLocal, engine, get_db
from backend.exporting import (
    export_filename as _get_export_filename,
)
from backend.exporting import (
    generate_shoe_rows as _generate_shoe_rows,
)
from backend.observability import RequestContextMiddleware
from backend.routers import health, insights
from backend.routers import runs as run_routes
from backend.routers import shoes as shoe_routes

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
    migrations.run_startup_migrations(engine, SessionLocal)
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
app.add_middleware(RequestContextMiddleware)
app.include_router(insights.router)
app.include_router(shoe_routes.router)
app.include_router(run_routes.router)
app.include_router(health.router)

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


# Compatibility aliases for callers that imported route functions from backend.main.
list_active = shoe_routes.list_active
list_retired = shoe_routes.list_retired
create_shoe = shoe_routes.create_shoe
update_shoe = shoe_routes.update_shoe
delete_shoe = shoe_routes.delete_shoe
_parse_strava_csv = run_routes._parse_strava_csv
_filter_strava_rows = run_routes._filter_strava_rows
_read_strava_upload = run_routes._read_strava_upload
_strava_preview = run_routes._strava_preview
preview_strava_import = run_routes.preview_strava_import
import_strava_runs = run_routes.import_strava_runs
list_strava_imports = run_routes.list_strava_imports
list_runs = run_routes.list_runs
create_run = run_routes.create_run
update_run = run_routes.update_run
delete_run = run_routes.delete_run


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


# Compatibility wrapper for tests and callers that imported this route from
# backend.main before the route groups were introduced.
def export_shoes(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    mode: str = Query("active", pattern="^(all|active|retired)$"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return insights.build_shoe_export(
        format,
        mode,
        current_user,
        db,
        row_generator=_generate_shoe_rows,
        filename_factory=_get_export_filename,
    )


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
