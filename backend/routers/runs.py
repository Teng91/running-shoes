"""Run log CRUD HTTP routes."""

from calendar import monthrange
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.database import get_db
from backend.services.mileage import apply_run_mileage_deltas
from backend.settings import settings

router = APIRouter(tags=["runs"])
MAX_RUNS_PER_USER = settings.max_runs_per_user


def _user_shoe_or_404(db: Session, user_id: int, shoe_id: int) -> models.Shoe:
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    return shoe


@router.get("/api/runs", response_model=list[schemas.RunOut])
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


@router.post("/api/runs", response_model=schemas.RunOut)
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
        apply_run_mileage_deltas(
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


@router.put("/api/runs/{run_id}", response_model=schemas.RunOut)
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
        apply_run_mileage_deltas(
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


@router.delete("/api/runs/{run_id}")
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
        apply_run_mileage_deltas(db, current_user.id, [run_values], -1)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}
