"""Shoe collection HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.database import get_db
from backend.dependencies import get_settings
from backend.forecasting import forecasts_for_shoes
from backend.routers.errors import service_errors
from backend.services import shoes as shoes_service
from backend.settings import Settings
from backend.shoe_metrics import shoe_metrics

router = APIRouter(tags=["shoes"])


def _shoe_outputs(db: Session, user_id: int, shoes: list[models.Shoe]) -> list[schemas.ShoeOut]:
    forecasts = forecasts_for_shoes(db, user_id, shoes)
    return [
        schemas.ShoeOut.model_validate(shoe).model_copy(
            update={
                **shoe_metrics(shoe),
                **{
                    key: value
                    for key, value in forecasts[shoe.id].items()
                    if key.startswith("forecast_")
                },
            }
        )
        for shoe in shoes
    ]


@router.get("/api/shoes/active", response_model=list[schemas.ShoeOut])
def list_active(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.Shoe)
        .filter(
            models.Shoe.is_retired.is_(False),
            models.Shoe.is_deleted.is_(False),
            models.Shoe.user_id == current_user.id,
        )
        .all()
    )
    return _shoe_outputs(db, current_user.id, rows)


@router.get("/api/shoes/retired", response_model=list[schemas.ShoeOut])
def list_retired(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.Shoe)
        .filter(
            models.Shoe.is_retired.is_(True),
            models.Shoe.is_deleted.is_(False),
            models.Shoe.user_id == current_user.id,
        )
        .all()
    )
    return _shoe_outputs(db, current_user.id, rows)


@router.post("/api/shoes", response_model=schemas.ShoeOut)
def create_shoe(
    payload: schemas.ShoeCreate,
    config: Settings = Depends(get_settings),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with service_errors():
        return _shoe_outputs(
            db,
            current_user.id,
            [
                shoes_service.create_shoe(
                    db, current_user.id, payload, max_shoes=config.max_shoes_per_user
                )
            ],
        )[0]


@router.put("/api/shoes/{shoe_id}", response_model=schemas.ShoeOut)
def update_shoe(
    shoe_id: int,
    payload: schemas.ShoeUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with service_errors():
        return _shoe_outputs(
            db, current_user.id, [shoes_service.update_shoe(db, current_user.id, shoe_id, payload)]
        )[0]


@router.delete("/api/shoes/{shoe_id}")
def delete_shoe(
    shoe_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with service_errors():
        return shoes_service.delete_shoe(db, current_user.id, shoe_id, expected_version)
