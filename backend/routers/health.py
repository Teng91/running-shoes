"""Unauthenticated liveness and dependency readiness probes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend import migrations
from backend.database import get_db

router = APIRouter(tags=["health"])
REQUIRED_TABLES = {"users", "shoes", "runs", "monthly_mileages"}


@router.get("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
def ready(db: Session = Depends(get_db)) -> dict[str, int | str]:
    """Require a responsive database with the current schema version."""
    try:
        db.execute(text("SELECT 1"))
        tables = set(inspect(db.get_bind()).get_table_names())
        if not REQUIRED_TABLES.issubset(tables):
            raise HTTPException(status_code=503, detail="database schema is incomplete")
        if "schema_metadata" not in tables:
            raise HTTPException(status_code=503, detail="database schema is not initialized")
        version_value = db.execute(
            text("SELECT value FROM schema_metadata WHERE key = 'schema_version'")
        ).scalar_one_or_none()
        version = int(version_value or 0)
        if version != migrations.CURRENT_SCHEMA_VERSION:
            raise HTTPException(status_code=503, detail="database schema is not current")
    except HTTPException:
        raise
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="database is unavailable") from exc
    return {"status": "ok", "schema_version": version}
