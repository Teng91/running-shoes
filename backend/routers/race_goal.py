"""Target-race HTTP endpoints (SPEC-065)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.clock import user_today
from backend.dependencies import get_db
from backend.read_models.race_readiness import race_goal_values
from backend.routers.errors import service_errors
from backend.services import race_goals

router = APIRouter(prefix="/api/race-goal", tags=["goals"])


@router.get("", response_model=schemas.RaceGoalOut | None)
def get_race_goal(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return race_goal_values(db, current_user.id)


@router.put("", response_model=schemas.RaceGoalOut)
def save_race_goal(
    payload: schemas.RaceGoalUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with service_errors():
        return race_goals.save_race_goal(db, current_user.id, payload, user_today(current_user))


@router.delete("")
def delete_race_goal(
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with service_errors():
        race_goals.delete_race_goal(db, current_user.id, expected_version)
    return {"deleted": True}
