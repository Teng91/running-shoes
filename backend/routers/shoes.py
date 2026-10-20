"""Shoe collection HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.database import get_db
from backend.forecasting import forecasts_for_shoes
from backend.settings import settings
from backend.shoe_metrics import shoe_metrics

router = APIRouter(tags=["shoes"])
MAX_SHOES_PER_USER = settings.max_shoes_per_user


def _shoe_outputs(db: Session, user_id: int, shoes: list[models.Shoe]) -> list[schemas.ShoeOut]:
    forecasts = forecasts_for_shoes(db, user_id, shoes)
    return [schemas.ShoeOut.model_validate(shoe).model_copy(update={
        **shoe_metrics(shoe),
        **{key: value for key, value in forecasts[shoe.id].items() if key.startswith("forecast_")},
    }) for shoe in shoes]


@router.get("/api/shoes/active", response_model=list[schemas.ShoeOut])
def list_active(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.Shoe).filter(
        models.Shoe.is_retired.is_(False),
        models.Shoe.is_deleted.is_(False),
        models.Shoe.user_id == current_user.id,
    ).all()
    return _shoe_outputs(db, current_user.id, rows)


@router.get("/api/shoes/retired", response_model=list[schemas.ShoeOut])
def list_retired(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.Shoe).filter(
        models.Shoe.is_retired.is_(True),
        models.Shoe.is_deleted.is_(False),
        models.Shoe.user_id == current_user.id,
    ).all()
    return _shoe_outputs(db, current_user.id, rows)


@router.post("/api/shoes", response_model=schemas.ShoeOut)
def create_shoe(
    payload: schemas.ShoeCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe_count = db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).count()
    if isinstance(shoe_count, int) and shoe_count >= MAX_SHOES_PER_USER:
        raise HTTPException(status_code=409, detail="跑鞋資料已達上限")
    shoe = models.Shoe(
        **payload.model_dump(),
        baseline_mileage=payload.mileage,
        user_id=current_user.id,
    )
    db.add(shoe)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(shoe)
    return _shoe_outputs(db, current_user.id, [shoe])[0]


@router.put("/api/shoes/{shoe_id}", response_model=schemas.ShoeOut)
def update_shoe(
    shoe_id: int,
    payload: schemas.ShoeUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    update_data = payload.model_dump(exclude_unset=True)
    supplied_version = update_data.pop("expected_version", None)
    current_version = int(getattr(shoe, "version", 0))
    if supplied_version is not None and supplied_version != current_version:
        raise HTTPException(status_code=409, detail="鞋款已被更新，請重新載入後再編輯")
    expected_version = current_version
    if "mileage" in update_data:
        logged_mileage = db.query(func.sum(models.Run.km)).filter(
            models.Run.user_id == current_user.id,
            models.Run.shoe_id == shoe_id,
        ).scalar()
        logged_total = round(float(logged_mileage or 0), 2)
        if float(update_data["mileage"]) + 0.005 < logged_total:
            raise HTTPException(
                status_code=400,
                detail=f"總里程不可低於逐筆跑步日誌合計 {logged_total:.2f} km",
            )
        update_data["baseline_mileage"] = round(
            float(update_data["mileage"]) - logged_total, 2
        )
    query = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id, models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    )
    query = query.filter(models.Shoe.version == expected_version)
    try:
        update_data["version"] = models.Shoe.version + 1
        changed = query.update(
            {getattr(models.Shoe, key): value for key, value in update_data.items()},
            synchronize_session=False,
        )
        if not changed:
            raise HTTPException(status_code=409, detail="鞋款已被更新，請重新載入後再編輯")
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(shoe)
    return _shoe_outputs(db, current_user.id, [shoe])[0]


@router.delete("/api/shoes/{shoe_id}")
def delete_shoe(
    shoe_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    version = getattr(shoe, "version", 0) if expected_version is None else expected_version
    try:
        changed = db.query(models.Shoe).filter(
            models.Shoe.id == shoe_id,
            models.Shoe.user_id == current_user.id,
            models.Shoe.is_deleted.is_(False),
            models.Shoe.version == version,
        ).update(
            {
                models.Shoe.is_deleted: True,
                models.Shoe.version: models.Shoe.version + 1,
            },
            synchronize_session=False,
        )
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="鞋款已被更新，請重新載入後再刪除",
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}
