"""Monthly mileage HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.dependencies import OperationKey, get_db, get_settings
from backend.routers.errors import service_errors
from backend.services import monthly as monthly_service
from backend.services.operations import legacy_operation
from backend.settings import Settings

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
    config: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    operation_key: OperationKey = None,
):
    with service_errors():
        if operation_key:
            return legacy_operation(db, current_user.id, "monthly.create", config, operation_key,
                                    payload.model_dump(exclude_unset=True))
        return monthly_service.create_monthly_mileage(db, current_user.id, payload)


@router.put("/{entry_id}", response_model=schemas.MonthlyMileageOut)
def update_monthly_mileage(
    entry_id: int,
    payload: schemas.MonthlyMileageUpdate,
    current_user: models.User = Depends(get_current_user),
    config: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    operation_key: OperationKey = None,
):
    with service_errors():
        if operation_key and payload.expected_version is not None:
            return legacy_operation(db, current_user.id, "monthly.update", config, operation_key,
                                    payload.model_dump(exclude_unset=True), entity_id=entry_id)
        return monthly_service.update_monthly_mileage(db, current_user.id, entry_id, payload)


@router.delete("/{entry_id}")
def delete_monthly_mileage(
    entry_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    config: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    operation_key: OperationKey = None,
):
    with service_errors():
        if operation_key and expected_version is not None:
            return legacy_operation(db, current_user.id, "monthly.delete", config, operation_key,
                                    {}, entity_id=entry_id, expected_version=expected_version)
        return monthly_service.delete_monthly_mileage(
            db, current_user.id, entry_id, expected_version
        )
