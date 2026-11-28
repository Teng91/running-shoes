"""FastAPI application factory and composition lifecycle."""

import asyncio
import logging
import mimetypes
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from threading import Lock
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import llm, migrations
from backend.backup_contract import MAX_BACKUP_BYTES
from backend.database import create_database_engine
from backend.mailer import smtp_mailer
from backend.middleware import (
    ApiRateLimitMiddleware,
    ApiRequestLimiter,
    SecurityHeadersMiddleware,
    UploadLimitMiddleware,
)
from backend.observability import RequestContextMiddleware
from backend.routers import (
    admin,
    agent,
    analytics,
    auth,
    exports,
    goals,
    health,
    monthly,
    race_goal,
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

# Responses carry X-Content-Type-Options: nosniff (SPEC-054), so a script or
# stylesheet served as text/plain would be refused. Pin the shell's types so a
# host MIME registry (for example on Windows) cannot change them.
STATIC_MEDIA_TYPES = (
    (".js", "text/javascript"),
    (".mjs", "text/javascript"),
    (".css", "text/css"),
    (".webmanifest", "application/manifest+json"),
)


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    validation = cast(RequestValidationError, exc)
    # Preserve loc/msg/type without echoing password, token or uploaded input.
    detail = [{key: error[key] for key in ("loc", "msg", "type")} for error in validation.errors()]
    return JSONResponse({"detail": detail, "error": {"code": "validation", "message": "輸入資料格式不正確"}}, status_code=422)


# SPEC-142: build inputs (shell templates, CSS sources, the asset manifest) stay in the
# image for builds and checks but are never served; the generated outputs are.
UNSERVED_FRONTEND_ENTRIES = frozenset({"templates", "css", "assets.json"})


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
            {"detail": exc.detail, "error": {"code": getattr(exc, "code", None) or {400: "invalid", 401: "unauthorized",
                403: "forbidden", 409: "conflict", 413: "too_large", 422: "validation"}.get(exc.status_code, "http_error"),
                "message": exc.detail}}, status_code=exc.status_code, headers=exc.headers
        )
    path = request.url.path
    if path.startswith(("/api/", "/docs", "/redoc", "/openapi.json")):
        return JSONResponse({"detail": exc.detail, "error": {"code": "not_found", "message": exc.detail}}, status_code=404, headers=exc.headers)
    frontend_dir: Path = request.app.state.frontend_dir
    try:
        candidate = (frontend_dir / path.lstrip("/")).resolve()
    except (OSError, ValueError):
        return _index_response(frontend_dir)
    root = frontend_dir.resolve()
    if root in candidate.parents and candidate.is_file():
        if candidate.relative_to(root).parts[0].casefold() not in UNSERVED_FRONTEND_ENTRIES:
            return FileResponse(candidate)
    return _index_response(frontend_dir)


logger = logging.getLogger("running_shoes.maintenance")
# SPEC-142: expired restore previews (up to 64 MiB each) are swept hourly, not only at startup.
PREVIEW_SWEEP_SECONDS = 3600.0


def _discard_expired_previews(session_factory: SessionFactory) -> int:
    with session_factory() as db:
        return account_restore.discard_expired_previews(db)


async def _sweep_expired_previews(session_factory: SessionFactory, interval: float) -> None:
    """Drop expired previews every ``interval`` seconds; a failed sweep waits for the next one."""
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(_discard_expired_previews, session_factory)
        except Exception:
            logger.exception("Expired restore preview sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config: Settings = app.state.settings
    migrations.run_startup_migrations(
        app.state.db_engine,
        app.state.session_factory,
        migration_password=config.migration_password,
    )
    seed_default_data(app.state.session_factory, config)
    _discard_expired_previews(app.state.session_factory)
    interval = getattr(app.state, "preview_sweep_seconds", PREVIEW_SWEEP_SECONDS)
    sweep = asyncio.create_task(_sweep_expired_previews(app.state.session_factory, interval))
    try:
        yield
    finally:
        sweep.cancel()
        with suppress(asyncio.CancelledError):
            await sweep


def create_app(
    config: Settings | None = None,
    *,
    db_engine: Engine | None = None,
    session_factory: SessionFactory | None = None,
    frontend_dir: Path | None = None,
) -> FastAPI:
    """Build an isolated application from explicit runtime dependencies.

    This is the only place that validates secrets and creates the default
    engine; importing backend modules performs no database or network I/O
    (``backend.settings`` only reads the environment and an optional ``.env``).
    """
    selected_settings = runtime_settings(config or default_settings)
    for suffix, media_type in STATIC_MEDIA_TYPES:
        mimetypes.add_type(media_type, suffix)
    if db_engine is None:
        selected_settings.database_dir.mkdir(parents=True, exist_ok=True)
        db_engine = create_database_engine(selected_settings.database_url)
    selected_session_factory = session_factory or sessionmaker(
        autocommit=False, autoflush=False, bind=db_engine
    )
    selected_frontend = (frontend_dir or selected_settings.frontend_dir).resolve()
    selected_frontend.mkdir(parents=True, exist_ok=True)

    # SPEC-071: no interactive API console in production. /openapi.json stays,
    # because release-check verifies the deployed route contract against it.
    interactive_docs = not selected_settings.is_production
    app = FastAPI(
        title="Running Shoes API", lifespan=lifespan,
        docs_url="/docs" if interactive_docs else None,
        redoc_url="/redoc" if interactive_docs else None,
    )
    app.state.settings = selected_settings
    app.state.db_engine = db_engine
    app.state.session_factory = selected_session_factory
    app.state.frontend_dir = selected_frontend
    # Memory is per process: one backup preview or restore at a time in this process.
    app.state.restore_slot = Lock()
    app.state.preview_sweep_seconds = PREVIEW_SWEEP_SECONDS
    # SPEC-079: None when SMTP is not configured; tests replace it with a fake sender.
    app.state.mailer = smtp_mailer(selected_settings)
    # One Strava CSV parse per process as well (SPEC-074).
    app.state.strava_upload_slot = Lock()
    # SPEC-093: the LLM adapter takes its key and limits from these settings, not from
    # environment reads at import time.
    llm.configure(llm.LLMConfig.from_settings(selected_settings))

    app.add_middleware(
        UploadLimitMiddleware,
        max_bytes=selected_settings.max_strava_request_bytes,
        max_backup_bytes=MAX_BACKUP_BYTES,
        max_api_bytes=selected_settings.max_api_body_bytes,
    )
    # The SPA and API share one origin, so no CORS middleware is installed:
    # browsers refuse cross-origin API reads (SPEC-054).
    # Outermost after the headers: a flood is turned away before uploads, sessions or routing.
    app.state.api_rate_limiter = ApiRequestLimiter()
    app.add_middleware(ApiRateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    for router in (
        auth.router,
        admin.router,
        goals.router,
        monthly.router,
        race_goal.router,
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
