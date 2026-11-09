"""Unauthenticated liveness and dependency readiness probes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import migrations
from backend.dependencies import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
def ready(db: Session = Depends(get_db)) -> dict[str, int | str]:
    """Require a responsive database with the current schema version."""
    try:
        version = migrations.ready_schema_version(db)
    except migrations.DatabaseNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "schema_version": version}
