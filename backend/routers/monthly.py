"""Monthly mileage HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.database import get_db

router = APIRouter(prefix="/api/monthly-mileage", tags=["monthly mileage"])


def _logged_km(db: Session, user_id: int, year: int, month: int) -> float:
    value = db.query(func.sum(models.Run.km)).filter(
        models.Run.user_id == user_id,
        models.Run.date.like(f"{year:04d}-{month:02d}-%"),
    ).scalar()
    return round(float(value or 0), 2)


@router.get("", response_model=list[schemas.MonthlyMileageOut])
def list_monthly_mileage(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == current_user.id,
    ).order_by(models.MonthlyMileage.year, models.MonthlyMileage.month).all()


@router.post("", response_model=schemas.MonthlyMileageOut)
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
    logged_total = _logged_km(db, current_user.id, payload.year, payload.month)
    if payload.km + 0.005 < logged_total:
        raise HTTPException(status_code=400, detail=f"月跑量不可低於逐筆跑步日誌合計 {logged_total:.2f} km")
    entry = models.MonthlyMileage(
        **payload.model_dump(),
        adjustment_km=round(payload.km - logged_total, 2),
        user_id=current_user.id,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="該月份已有紀錄") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=schemas.MonthlyMileageOut)
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
    expected_version = update_data.pop("expected_version", getattr(entry, "version", 0))
    new_month = update_data.get("month", entry.month)
    new_year = update_data.get("year", entry.year)
    if ("year" in update_data or "month" in update_data) and (
        new_year != entry.year or new_month != entry.month
    ):
        if _logged_km(db, current_user.id, entry.year, entry.month) > 0.005:
            raise HTTPException(
                status_code=400,
                detail="此月份已有逐筆跑步日誌，請先修改跑步日期，不能直接移動月份",
            )
        clash = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.user_id == current_user.id,
            models.MonthlyMileage.year == new_year,
            models.MonthlyMileage.month == new_month,
            models.MonthlyMileage.id != entry_id,
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="該月份已有紀錄")
    desired_total = float(update_data.get("km", entry.km))
    logged_total = _logged_km(db, current_user.id, new_year, new_month)
    if desired_total + 0.005 < logged_total:
        raise HTTPException(status_code=400, detail=f"月跑量不可低於逐筆跑步日誌合計 {logged_total:.2f} km")
    update_data["adjustment_km"] = round(desired_total - logged_total, 2)
    try:
        changed = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.id == entry_id,
            models.MonthlyMileage.user_id == current_user.id,
            models.MonthlyMileage.version == expected_version,
        ).update(
            {
                **{getattr(models.MonthlyMileage, key): value for key, value in update_data.items()},
                models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
            },
            synchronize_session=False,
        )
        if not changed:
            raise HTTPException(status_code=409, detail="月跑量已被更新，請重新載入後再編輯")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="該月份已有紀錄") from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_monthly_mileage(
    entry_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.id == entry_id,
        models.MonthlyMileage.user_id == current_user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Monthly mileage not found")
    version = getattr(entry, "version", 0) if expected_version is None else expected_version
    logged_total = _logged_km(db, current_user.id, entry.year, entry.month)
    try:
        query = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.id == entry_id,
            models.MonthlyMileage.user_id == current_user.id,
            models.MonthlyMileage.version == version,
        )
        if logged_total:
            changed = query.update(
                {
                    models.MonthlyMileage.adjustment_km: 0,
                    models.MonthlyMileage.km: logged_total,
                    models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
                },
                synchronize_session=False,
            )
        else:
            changed = query.delete(synchronize_session=False)
        if not changed:
            raise HTTPException(status_code=409, detail="月跑量已被更新，請重新載入後再刪除")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}
