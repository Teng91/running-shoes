"""Monthly mileage HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.database import get_db
from backend.routers.errors import service_errors
from backend.services import monthly as monthly_service

router = APIRouter(prefix="/api/monthly-mileage", tags=["monthly mileage"])


@router.get("", response_model=list[schemas.MonthlyMileageOut])
def list_monthly_mileage(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.MonthlyMileage)
        .filter(
            models.MonthlyMileage.user_id == current_user.id,
        )
        .order_by(models.MonthlyMileage.year, models.MonthlyMileage.month)
        .all()
    )


@router.post("", response_model=schemas.MonthlyMileageOut)
def create_monthly_mileage(
    payload: schemas.MonthlyMileageCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with service_errors():
        return monthly_service.create_monthly_mileage(db, current_user.id, payload)


@router.put("/{entry_id}", response_model=schemas.MonthlyMileageOut)
def update_monthly_mileage(
    entry_id: int,
    payload: schemas.MonthlyMileageUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with service_errors():
        return monthly_service.update_monthly_mileage(db, current_user.id, entry_id, payload)


@router.delete("/{entry_id}")
def delete_monthly_mileage(
    entry_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with service_errors():
        return monthly_service.delete_monthly_mileage(
            db, current_user.id, entry_id, expected_version
        )
