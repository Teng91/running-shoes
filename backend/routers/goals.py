"""Running-goal HTTP endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend import goals as goal_service
from backend import models, schemas
from backend.auth import get_current_user
from backend.database import get_db
from backend.routers.errors import service_errors
from backend.services import goals

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
    db: Session = Depends(get_db),
):
    with service_errors():
        return goals.update_goal(db, current_user.id, payload)


@router.get("/progress")
def running_goal_progress(
    year: int = Query(ge=1900, le=2100),
    month: int = Query(ge=1, le=12),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return goal_service.goal_progress(db, current_user.id, year, month)
