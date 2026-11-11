"""FastAPI application factory and composition lifecycle."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import migrations
from backend.backup_contract import MAX_BACKUP_BYTES
from backend.database import create_database_engine
from backend.middleware import StravaUploadLimitMiddleware
from backend.observability import RequestContextMiddleware
from backend.routers import (
    agent,
    analytics,
    auth,
    exports,
    goals,
    health,
    monthly,
    reports,
    runs,
    shoes,
    spending,
    strava,
    workspace,
)
from backend.seeding import seed_default_data
from backend.services import account_restore
from backend.settings import Settings, runtime_settings
from backend.settings import settings as default_settings

SessionFactory = Callable[[], Session]


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    validation = cast(RequestValidationError, exc)
    # Preserve loc/msg/type without echoing password, token or uploaded input.
    detail = [{key: error[key] for key in ("loc", "msg", "type")} for error in validation.errors()]
    return JSONResponse({"detail": detail, "error": {"code": "validation", "message": "輸入資料格式不正確"}}, status_code=422)


def _index_response(frontend_dir: Path) -> FileResponse:
    return FileResponse(
        frontend_dir / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    """Serve SPA assets/fallbacks while preserving JSON API errors."""
    exc = cast(StarletteHTTPException, exc)
    if exc.status_code != 404:
        return JSONResponse(
            {"detail": exc.detail, "error": {"code": {400: "invalid", 401: "unauthorized", 403: "capacity",
                409: "conflict", 413: "too_large", 422: "validation"}.get(exc.status_code, "http_error"),
                "message": exc.detail}}, status_code=exc.status_code, headers=exc.headers
        )
    path = request.url.path
    if path.startswith(("/api/", "/docs", "/openapi.json")):
        return JSONResponse({"detail": exc.detail, "error": {"code": "not_found", "message": exc.detail}}, status_code=404, headers=exc.headers)
    frontend_dir: Path = request.app.state.frontend_dir
    try:
        candidate = (frontend_dir / path.lstrip("/")).resolve()
    except (OSError, ValueError):
        return _index_response(frontend_dir)
    if frontend_dir.resolve() in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    return _index_response(frontend_dir)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config: Settings = app.state.settings
    migrations.run_startup_migrations(
        app.state.db_engine,
        app.state.session_factory,
        migration_password=config.migration_password,
    )
    seed_default_data(app.state.session_factory, config)
    with app.state.session_factory() as db:
        account_restore.discard_expired_previews(db)
    yield


def create_app(
    config: Settings | None = None,
    *,
    db_engine: Engine | None = None,
    session_factory: SessionFactory | None = None,
    frontend_dir: Path | None = None,
) -> FastAPI:
    """Build an isolated application from explicit runtime dependencies.

    This is the only place that validates secrets and creates the default
    engine; importing backend modules performs no I/O.
    """
    selected_settings = runtime_settings(config or default_settings)
    if db_engine is None:
        selected_settings.database_dir.mkdir(parents=True, exist_ok=True)
        db_engine = create_database_engine(selected_settings.database_url)
    selected_session_factory = session_factory or sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine
    )
    selected_frontend = (frontend_dir or selected_settings.frontend_dir).resolve()
    selected_frontend.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Running Shoes API", lifespan=lifespan)
    app.state.settings = selected_settings
    app.state.db_engine = db_engine
    app.state.session_factory = selected_session_factory
    app.state.frontend_dir = selected_frontend
    # Memory is per process: one backup preview or restore at a time in this process.
    app.state.restore_slot = Lock()

    app.add_middleware(
        StravaUploadLimitMiddleware,
        max_bytes=selected_settings.max_strava_request_bytes,
        max_backup_bytes=MAX_BACKUP_BYTES,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    for router in (
        auth.router,
        goals.router,
        monthly.router,
        agent.router,
        reports.router,
        analytics.router,
        exports.router,
        spending.router,
        shoes.router,
        runs.router,
        strava.router,
        health.router,
        workspace.router,
    ):
        app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    return app
