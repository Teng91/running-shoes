"""Run log CRUD HTTP routes."""

from calendar import monthrange
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.database import get_db
from backend.read_models.runs import month_run_summary, year_run_summary
from backend.services import run_requests
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
    day: int | None = Query(default=None, ge=1, le=31),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail="month requires year")
    if day is not None and (month is None or year is None):
        raise HTTPException(status_code=422, detail="day requires year and month")
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
        if day is not None:
            if month is None or day > monthrange(year, month)[1]:
                raise HTTPException(status_code=422, detail="invalid calendar day")
            query = query.filter(models.Run.date == f"{year:04d}-{month:02d}-{day:02d}")
    query = query.order_by(models.Run.date.desc(), models.Run.id.desc()).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


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
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(
        alias="Idempotency-Key", min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )] = None,
):
    fingerprint = run_requests.payload_hash(payload.model_dump())
    receipt = None
    try:
        if idempotency_key:
            previous = run_requests.replay(db, current_user.id, idempotency_key, fingerprint)
            if previous is not None:
                return previous
            receipt = models.RunCreationRequest(
                user_id=current_user.id, request_key=idempotency_key, payload_hash=fingerprint
            )
            db.add(receipt)
            # Reserve the unique key before changing mileage. SQLite serializes
            # competing writers; a loser rolls back and replays the winner.
            db.flush()
        _user_shoe_or_404(db, current_user.id, payload.shoe_id)
        run_count = db.query(models.Run).filter(models.Run.user_id == current_user.id).count()
        if isinstance(run_count, int) and run_count >= MAX_RUNS_PER_USER:
            raise HTTPException(status_code=409, detail="跑步紀錄已達上限")
        run = models.Run(**payload.model_dump(), user_id=current_user.id)
        db.add(run)
        apply_run_mileage_deltas(
            db,
            current_user.id,
            [(payload.shoe_id, payload.date, payload.km)],
            1,
        )
        if receipt is not None:
            db.flush()
            receipt.response_json = schemas.RunOut.model_validate(run).model_dump(mode="json")
        db.commit()
    except run_requests.RequestConflictError:
        db.rollback()
        raise HTTPException(status_code=409, detail="此操作識別碼已用於不同內容，請修改後重新送出") from None
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            try:
                previous = run_requests.replay(db, current_user.id, idempotency_key, fingerprint)
            except run_requests.RequestConflictError:
                raise HTTPException(status_code=409, detail="此操作識別碼已用於不同內容") from None
            if previous is not None:
                return previous
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run


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
