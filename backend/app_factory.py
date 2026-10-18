"""FastAPI application factory and composition lifecycle."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import migrations
from backend.database import SessionLocal, engine, get_db
from backend.middleware import StravaUploadLimitMiddleware
from backend.observability import RequestContextMiddleware
from backend.routers import agent, auth, goals, health, insights, monthly, reports, runs, shoes
from backend.seeding import seed_default_data
from backend.settings import Settings
from backend.settings import settings as default_settings

SessionFactory = Callable[[], Session]


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
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )
    path = request.url.path
    if path.startswith(("/api/", "/docs", "/openapi.json")):
        return JSONResponse({"detail": exc.detail}, status_code=404, headers=exc.headers)
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
    yield


def create_app(
    config: Settings | None = None,
    *,
    db_engine: Engine | None = None,
    session_factory: SessionFactory | None = None,
    frontend_dir: Path | None = None,
) -> FastAPI:
    """Build an isolated application from explicit runtime dependencies."""
    selected_settings = config or default_settings
    selected_engine = db_engine or engine
    selected_session_factory = session_factory or SessionLocal
    selected_frontend = (frontend_dir or selected_settings.frontend_dir).resolve()
    selected_frontend.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Running Shoes API", lifespan=lifespan)
    app.state.settings = selected_settings
    app.state.db_engine = selected_engine
    app.state.session_factory = selected_session_factory
    app.state.frontend_dir = selected_frontend

    def app_database_session():
        db = selected_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = app_database_session
    app.add_middleware(StravaUploadLimitMiddleware)
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
        insights.router,
        shoes.router,
        runs.router,
        health.router,
    ):
        app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    return app
