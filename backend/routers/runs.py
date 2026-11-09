"""Run log CRUD HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.dependencies import OperationKey, get_db, get_settings
from backend.read_models import runs as run_reads
from backend.read_models.runs import is_calendar_day, month_run_summary, year_run_summary
from backend.routers.errors import service_errors
from backend.services import runs as runs_service
from backend.services.operations import legacy_operation
from backend.settings import Settings

router = APIRouter(tags=["runs"])


@router.get("/api/runs", response_model=list[schemas.RunOut])
def list_runs(
    year: int | None = Query(default=None, ge=1900, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    day: int | None = Query(default=None, ge=1, le=31),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail="month requires year")
    if day is not None and (month is None or year is None):
        raise HTTPException(status_code=422, detail="day requires year and month")
    if day is not None and year is not None and month is not None and not is_calendar_day(year, month, day):
        raise HTTPException(status_code=422, detail="invalid calendar day")
    return run_reads.list_runs(
        db, current_user.id, year=year, month=month, day=day, limit=limit, offset=offset
    )


@router.get("/api/runs/summary")
def run_summary(
    year: int = Query(ge=1900, le=2100),
    month: int = Query(ge=1, le=12),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return month_run_summary(db, current_user.id, year, month)


@router.post("/api/runs", response_model=schemas.RunOut)
def create_run(
    payload: schemas.RunCreate,
    config: Settings = Depends(get_settings),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key", min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
        ),
    ] = None,
):
    with service_errors():
        if idempotency_key:
            return legacy_operation(db, current_user.id, "run.create", config, idempotency_key, payload.model_dump(exclude_unset=True))
        return runs_service.create_run(
            db, current_user.id, payload, max_runs=config.max_runs_per_user
        )


@router.get("/api/runs/year-summary")
def annual_summary(
    year: int = Query(ge=1900, le=2100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return year_run_summary(db, current_user.id, year)


@router.put("/api/runs/{run_id}", response_model=schemas.RunOut)
def update_run(
    run_id: int,
    payload: schemas.RunUpdate,
    current_user: models.User = Depends(get_current_user),
    config: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    operation_key: OperationKey = None,
):
    with service_errors():
        if operation_key and payload.expected_version is not None:
            return legacy_operation(db, current_user.id, "run.update", config, operation_key,
                                    payload.model_dump(exclude_unset=True), entity_id=run_id)
        return runs_service.update_run(db, current_user.id, run_id, payload)


@router.delete("/api/runs/{run_id}")
def delete_run(
    run_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    config: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    operation_key: OperationKey = None,
):
    with service_errors():
        if operation_key and expected_version is not None:
            return legacy_operation(db, current_user.id, "run.delete", config, operation_key,
                                    {}, entity_id=run_id, expected_version=expected_version)
        return runs_service.delete_run(db, current_user.id, run_id, expected_version)
