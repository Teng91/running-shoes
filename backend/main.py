import csv
import io
import json
import os
import re
import time
from collections import deque
from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import cast

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import Table, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import agent, llm, models, schemas
from backend.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from backend.database import Base, SessionLocal, engine, get_db

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
MODEL_REFRESH_COOLDOWN_SECONDS = max(
    1, int(os.environ.get("MODEL_REFRESH_COOLDOWN_SECONDS", "60"))
)
_agent_rate_events: dict[int, deque[float]] = {}
_agent_ip_rate_events: dict[str, deque[float]] = {}
_agent_global_rate_events: dict[str, deque[float]] = {}
_auth_rate_events: dict[str, deque[float]] = {}
_auth_global_rate_events: dict[str, deque[float]] = {}
_model_refresh_times: dict[int, float] = {}
_agent_rate_lock = Lock()
_registration_lock = Lock()


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
    """Use Fly's authenticated client-IP header, falling back to the peer address."""
    fly_ip = request.headers.get("fly-client-ip", "").strip()
    if fly_ip:
        return fly_ip[:64]
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


def _enforce_auth_rate_limit(request: Request) -> None:
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


def _enforce_agent_request_limits(request: Request, user_id: int) -> None:
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
                models.MonthlyMileage(user_id=joy_user.id, year=y, month=m, km=km)
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
        # Other was a temporary category; remove it from any JSON arrays.
        # Use a compatible approach: find ids with 'Other' and update individually.
        # This avoids "UPDATE ... FROM json_each" which requires SQLite 3.38+.
        # Use `shoes.id` (our primary key) to avoid ambiguous column in join.
        rows_with_other = conn.execute(text("""
            SELECT shoes.id FROM shoes,
            json_each(categories)
            WHERE json_each.value = 'Other'
        """)).fetchall()
        for (sid,) in rows_with_other:
            conn.execute(text("""
                UPDATE shoes
                SET categories = json_remove(categories,
                    (SELECT '$[' || key || ']'
                     FROM json_each(categories)
                     WHERE value = 'Other'
                     LIMIT 1))
                WHERE id = :sid
            """), {"sid": sid})

    seed_default_data()
    yield


app = FastAPI(title="Running Shoes API", lifespan=lifespan)

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
            return JSONResponse({"detail": exc.detail}, status_code=404)
        # Resolve and ensure the file lives inside frontend_dir — otherwise
        # a path like "/../shoes.db" could escape and serve arbitrary files.
        try:
            candidate = (frontend_dir / path.lstrip("/")).resolve()
        except (OSError, ValueError):
            return _index_response()
        if frontend_dir.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return _index_response()
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ── Auth Routes ───────────────────────────────────────────────
@app.post("/api/auth/register", response_model=schemas.UserOut)
def register(request: Request, payload: schemas.UserCreate, db: Session = Depends(get_db)):
    _enforce_auth_rate_limit(request)
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
    _enforce_auth_rate_limit(request)
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_access_token(data={"sub": user.username})
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
    _enforce_auth_rate_limit(request)
    if len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or old password")
    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or old password")
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
        models.Shoe.user_id == current_user.id,
    ).all()


@app.get("/api/shoes/retired", response_model=list[schemas.ShoeOut])
def list_retired(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Shoe).filter(
        models.Shoe.is_retired.is_(True),
        models.Shoe.user_id == current_user.id,
    ).all()


@app.post("/api/shoes", response_model=schemas.ShoeOut)
def create_shoe(
    payload: schemas.ShoeCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe_count = db.query(models.Shoe).filter(models.Shoe.user_id == current_user.id).count()
    if isinstance(shoe_count, int) and shoe_count >= MAX_SHOES_PER_USER:
        raise HTTPException(status_code=409, detail="跑鞋資料已達上限")
    shoe = models.Shoe(**payload.model_dump(), user_id=current_user.id)
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
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(shoe, k, v)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(shoe)
    return shoe


@app.delete("/api/shoes/{shoe_id}")
def delete_shoe(
    shoe_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == current_user.id,
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    if db.query(models.Run).filter(
        models.Run.user_id == current_user.id,
        models.Run.shoe_id == shoe_id,
    ).first():
        raise HTTPException(
            status_code=409,
            detail="這雙跑鞋已有跑步紀錄，請保留或移至退役",
        )
    db.delete(shoe)
    try:
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
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    return shoe


_STRAVA_HEADERS = {
    "id": ("活動 ID", "Activity ID"),
    "date": ("活動日期", "Activity Date"),
    "type": ("活動類型", "Activity Type"),
    "gear": ("活動裝備", "Gear"),
    "distance": ("距離", "Distance"),
}
_STRAVA_RUN_TYPES = {"跑步", "Run", "TrailRun", "Trail Run", "VirtualRun", "Virtual Run"}


def _strava_field(headers: Sequence[str], key: str) -> str | None:
    for candidate in _STRAVA_HEADERS[key]:
        if candidate in headers:
            return candidate
    return None


def _parse_strava_date(value: str) -> str:
    text_value = value.strip()
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text_value)
    if match:
        return datetime.strptime(
            f"{match.group(1)}-{match.group(2)}-{match.group(3)}", "%Y-%m-%d"
        ).replace(tzinfo=UTC).date().isoformat()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text_value[:10], fmt).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    raise ValueError("invalid date")


def _normalize_gear(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _parse_strava_csv(raw: bytes) -> tuple[list[dict[str, object]], int, list[str]]:
    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="無法讀取 CSV，請使用 UTF-8 編碼") from exc
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    fields = {key: _strava_field(headers, key) for key in _STRAVA_HEADERS}
    missing = [key for key, field in fields.items() if field is None]
    if missing:
        raise HTTPException(status_code=400, detail="CSV 缺少必要欄位：" + ", ".join(missing))
    rows: list[dict[str, object]] = []
    invalid = 0
    warnings: list[str] = []
    for row in reader:
        if (row.get(fields["type"] or "") or "").strip() not in _STRAVA_RUN_TYPES:
            continue
        try:
            activity_id = (row.get(fields["id"] or "") or "").strip()
            date_value = _parse_strava_date(row.get(fields["date"] or "") or "")
            distance_m = float((row.get(fields["distance"] or "") or "").replace(",", "").strip())
            if not activity_id or distance_m <= 0 or distance_m > 1_000_000:
                raise ValueError("invalid activity")
        except (TypeError, ValueError):
            invalid += 1
            continue
        rows.append({
            "strava_id": activity_id[:100],
            "date": date_value,
            "km": round(distance_m / 1000, 2),
            "gear": (row.get(fields["gear"] or "") or "").strip(),
        })
    if invalid:
        warnings.append(f"已略過 {invalid} 筆格式不完整的跑步活動")
    return rows, invalid, warnings


def _filter_strava_rows(
    rows: list[dict[str, object]], start_date: str, end_date: str
) -> tuple[list[dict[str, object]], int]:
    normalized_dates: list[str] = []
    for value, label in ((start_date, "起始"), (end_date, "結束")):
        if not value:
            normalized_dates.append("")
            continue
        try:
            normalized_dates.append(
                datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).date().isoformat()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{label}日期格式錯誤") from exc
    normalized_start, normalized_end = normalized_dates
    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise HTTPException(status_code=400, detail="起始日期不可晚於結束日期")
    filtered = [
        row for row in rows
        if (not normalized_start or str(row["date"]) >= normalized_start)
        and (not normalized_end or str(row["date"]) <= normalized_end)
    ]
    return filtered, len(rows) - len(filtered)


def _strava_preview(db: Session, user_id: int, rows: list[dict[str, object]], invalid: int, warnings: list[str]) -> dict[str, object]:
    existing_ids = {
        value[0] for value in db.query(models.Run.strava_id).filter(
            models.Run.user_id == user_id, models.Run.strava_id.isnot(None)
        ).all()
    }
    shoes = db.query(models.Shoe).filter(models.Shoe.user_id == user_id).all()
    shoe_by_key = {_normalize_gear(f"{shoe.brand} {shoe.model}"): shoe for shoe in shoes}
    groups: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    duplicate_count = 0
    for row in rows:
        strava_id = str(row["strava_id"])
        if strava_id in existing_ids or strava_id in seen:
            duplicate_count += 1
        seen.add(strava_id)
        gear = str(row["gear"])
        group = groups.setdefault(gear, {"gear": gear, "count": 0, "km": 0.0})
        group["count"] = int(cast(int, group["count"])) + 1
        group["km"] = round(float(cast(float, group["km"])) + float(cast(float, row["km"])), 2)
    for group in groups.values():
        shoe = shoe_by_key.get(_normalize_gear(str(group["gear"])))
        group["suggested_shoe_id"] = shoe.id if shoe else None
        group["shoe_name"] = f"{shoe.brand} {shoe.model}" if shoe else None
    return {
        "total_rows": len(rows) + invalid,
        "run_count": len(rows),
        "duplicate_count": duplicate_count,
        "invalid_count": invalid,
        "gear_groups": sorted(groups.values(), key=lambda group: str(group["gear"])),
        "warnings": warnings,
    }


@app.post("/api/runs/import/strava/preview")
async def preview_strava_import(
    file: UploadFile = File(...),
    start_date: str = Form(""),
    end_date: str = Form(""),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV 檔案不可超過 10 MB")
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
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV 檔案不可超過 10 MB")
    rows, invalid, _ = _parse_strava_csv(raw)
    rows, filtered_out = _filter_strava_rows(rows, start_date, end_date)
    shoes = {shoe.id: shoe for shoe in db.query(models.Shoe).filter(models.Shoe.user_id == current_user.id).all()}
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
    db.add_all(runs_to_add)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="部分 Strava 活動已存在，請重新預覽") from exc
    return {
        "imported": len(runs_to_add),
        "skipped_duplicate": skipped_duplicate,
        "skipped_unmapped": skipped_unmapped,
        "skipped_invalid": invalid,
        "filtered_out": filtered_out,
        "total_run_rows": len(rows),
    }


@app.get("/api/runs", response_model=list[schemas.RunOut])
def list_runs(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Run).filter(
        models.Run.user_id == current_user.id,
    ).order_by(models.Run.date.desc(), models.Run.id.desc()).all()


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
    if "shoe_id" in update_data:
        _user_shoe_or_404(db, current_user.id, update_data["shoe_id"])
    for key, value in update_data.items():
        setattr(run, key, value)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run


@app.delete("/api/runs/{run_id}")
def delete_run(
    run_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(models.Run).filter(
        models.Run.id == run_id,
        models.Run.user_id == current_user.id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}


# ── Monthly Mileage Routes ──
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

    entry = models.MonthlyMileage(**payload.model_dump(), user_id=current_user.id)
    db.add(entry)
    try:
        db.commit()
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
    new_month = update_data.get("month", entry.month)
    new_year = update_data.get("year", entry.year)

    # Check uniqueness if year/month are changing
    if ("year" in update_data or "month" in update_data) and (
        new_year != entry.year or new_month != entry.month
    ):
        clash = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.user_id == current_user.id,
            models.MonthlyMileage.year == new_year,
            models.MonthlyMileage.month == new_month,
            models.MonthlyMileage.id != entry_id,
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="該月份已有紀錄")

    for k, v in update_data.items():
        setattr(entry, k, v)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


@app.delete("/api/monthly-mileage/{entry_id}")
def delete_monthly_mileage(
    entry_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.id == entry_id,
        models.MonthlyMileage.user_id == current_user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Monthly mileage not found")
    db.delete(entry)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}


# ── Export Routes ─────────────────────────────────────────────────
def _spreadsheet_safe(value):
    """Prevent user-controlled text becoming a CSV/XLSX formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _generate_shoe_rows(shoes: list[models.Shoe], include_retired_status: bool = True):
    """Generate CSV rows for shoes with all fields."""
    for s in shoes:
        status = "已退役" if s.is_retired else "使用中"
        discount = round(s.price / s.orig_price * 100, 2) if s.orig_price > 0 else 0
        cost_per_km = round(s.price / s.mileage, 2) if s.mileage > 0 else 0
        expected_cost = round(s.price / s.expected_mileage, 2) if s.expected_mileage > 0 else 0
        life_pct = round(s.mileage / s.expected_mileage * 100, 2) if s.expected_mileage > 0 else 0

        row = {
            "品牌": _spreadsheet_safe(s.brand),
            "鞋款": _spreadsheet_safe(s.model),
            "購買日期": _spreadsheet_safe(s.date),
            "尺寸": _spreadsheet_safe(s.size),
            "買價": int(s.price),
            "原價": int(s.orig_price),
            "折數(%)": discount,
            "跑鞋里程(km)": s.mileage,
            "預期里程(km)": s.expected_mileage,
            "每km成本": cost_per_km,
            "預期每km成本": expected_cost,
            "生命進度(%)": life_pct,
            "月跑量(km)": s.monthly_km,
            "類別": _spreadsheet_safe(", ".join(s.categories) if s.categories else ""),
        }
        if include_retired_status:
            row["狀態"] = status
        yield row


def _get_export_filename(format: str, mode: str) -> str:
    """Generate export filename with timestamp."""
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return f"running_shoes_{mode}_{timestamp}.{format}"


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
    query = db.query(models.Shoe).filter(models.Shoe.user_id == current_user.id)
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
def list_agent_providers():
    """回傳 provider/model 清單（含 key 是否已設定）。"""
    return llm.list_providers()


@app.post("/api/agent/models/refresh")
def refresh_agent_models(
    current_user: models.User = Depends(get_current_user),
):
    """強制刷新 OpenRouter 免費模型快取，回傳更新後的 provider/model 清單。"""
    _enforce_model_refresh_cooldown(current_user.id)
    return llm.list_providers(force=True)


@app.post("/api/agent/chat/stream")
def agent_chat_stream(
    request: Request,
    payload: schemas.AgentChatRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 串流版：與 /api/agent/chat 相同，但 LLM token 會逐字即時送達。"""
    _enforce_agent_request_limits(request, current_user.id)
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
