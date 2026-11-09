"""Running-goal HTTP endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend import goals as goal_service
from backend import models, schemas
from backend.auth import get_current_user
from backend.dependencies import OperationKey, get_db, get_settings
from backend.routers.errors import service_errors
from backend.services import goals
from backend.services.operations import legacy_operation
from backend.settings import Settings

router = APIRouter(prefix="/api/running-goal", tags=["goals"])


@router.get("", response_model=schemas.RunningGoalOut)
def get_running_goal(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return goal_service.goal_values(db, current_user.id)


@router.put("", response_model=schemas.RunningGoalOut)
def update_running_goal(
    payload: schemas.RunningGoalUpdate,
    current_user: models.User = Depends(get_current_user),
    config: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    operation_key: OperationKey = None,
):
    with service_errors():
        if operation_key and payload.expected_version is not None:
            return legacy_operation(db, current_user.id, "goal.update", config, operation_key,
                                    payload.model_dump(exclude_unset=True))
        return goals.update_goal(db, current_user.id, payload)


@router.get("/progress")
def running_goal_progress(
    year: int = Query(ge=1900, le=2100),
    month: int = Query(ge=1, le=12),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return goal_service.goal_progress(db, current_user.id, year, month)


@router.get("/year")
def running_goal_year(
    year: int = Query(ge=1900, le=2100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return goal_service.year_goal_overview(db, current_user.id, year)
