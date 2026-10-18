import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import ClassVar

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend import migrations, models
from backend.auth import get_current_user, get_password_hash
from backend.database import SessionLocal, engine, get_db
from backend.exporting import (
    export_filename as _get_export_filename,
)
from backend.exporting import (
    generate_shoe_rows as _generate_shoe_rows,
)
from backend.observability import RequestContextMiddleware
from backend.routers import agent as agent_routes
from backend.routers import auth as auth_routes
from backend.routers import goals as goal_routes
from backend.routers import health, insights
from backend.routers import monthly as monthly_routes
from backend.routers import reports as report_routes
from backend.routers import runs as run_routes
from backend.routers import shoes as shoe_routes

MAX_SHOES_PER_USER = max(1, int(os.environ.get("MAX_SHOES_PER_USER", "500")))
MAX_RUNS_PER_USER = max(1, int(os.environ.get("MAX_RUNS_PER_USER", "5000")))
MAX_STRAVA_CSV_BYTES = 10 * 1024 * 1024
MAX_STRAVA_REQUEST_BYTES = MAX_STRAVA_CSV_BYTES + 1024 * 1024
MAX_STRAVA_CSV_ROWS = 50_000
MAX_STRAVA_IMPORT_HISTORY_PER_USER = 50


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
app.include_router(auth_routes.router)
app.include_router(goal_routes.router)
app.include_router(monthly_routes.router)
app.include_router(agent_routes.router)
app.include_router(report_routes.router)
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



# Compatibility aliases for callers that imported route functions from backend.main.
register = auth_routes.register
login = auth_routes.login
read_current_user = auth_routes.read_current_user
change_password = auth_routes.change_password
get_running_goal = goal_routes.get_running_goal
update_running_goal = goal_routes.update_running_goal
list_monthly_mileage = monthly_routes.list_monthly_mileage
create_monthly_mileage = monthly_routes.create_monthly_mileage
update_monthly_mileage = monthly_routes.update_monthly_mileage
delete_monthly_mileage = monthly_routes.delete_monthly_mileage
list_agent_providers = agent_routes.list_agent_providers
refresh_agent_models = agent_routes.refresh_agent_models
agent_chat_stream = agent_routes.agent_chat_stream
generate_monthly_report = report_routes.generate_monthly_report
list_monthly_reports = report_routes.list_monthly_reports
get_monthly_report = report_routes.get_monthly_report
_local_today = report_routes._local_today

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


# Compatibility wrapper preserves injectable export collaborators for callers/tests.
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
