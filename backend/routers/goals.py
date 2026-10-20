"""Running-goal HTTP endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend import goals as goal_service
from backend import models, schemas
from backend.auth import get_current_user
from backend.database import get_db

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
    payload_data = payload.model_dump()
    expected_version = payload_data.pop("expected_version", None)
    if expected_version is None:
        current_version = db.query(models.RunningGoal.version).filter(
            models.RunningGoal.user_id == current_user.id
        ).scalar()
        expected_version = int(current_version or 0)
    insert_statement = sqlite_insert(models.RunningGoal).values(
        user_id=current_user.id,
        version=1,
        start_year=payload.start_year,
        monthly_km=payload.monthly_km,
        yearly_km=payload.monthly_km * 12,
    )
    statement = insert_statement.on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "start_year": payload.start_year,
            "monthly_km": payload.monthly_km,
            "yearly_km": payload.monthly_km * 12,
            "version": models.RunningGoal.version + 1,
        },
        where=models.RunningGoal.version == expected_version,
    ).returning(models.RunningGoal.id)
    try:
        changed_id = db.execute(statement).scalar_one_or_none()
        if changed_id is None:
            raise HTTPException(status_code=409, detail="跑量目標已被更新，請重新載入後再編輯")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return goal_service.goal_values(db, current_user.id)


@router.get("/progress")
def running_goal_progress(
    year: int = Query(ge=1900, le=2100),
    month: int = Query(ge=1, le=12),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return goal_service.goal_progress(db, current_user.id, year, month)
