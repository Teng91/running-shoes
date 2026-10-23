"""User-scoped running-goal writes and optimistic concurrency."""
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend import goals as goal_service
from backend import models, schemas
from backend.services.errors import Conflict
from backend.services.transactions import write_transaction


def update_goal(db: Session, user_id: int, payload: schemas.RunningGoalUpdate):
    with write_transaction(db, user_id, reason="goal.update"):
        payload_data = payload.model_dump()
        expected_version = payload_data.pop("expected_version", None)
        if expected_version is None:
            current_version = db.query(models.RunningGoal.version).filter(
                models.RunningGoal.user_id == user_id
            ).scalar()
            expected_version = int(current_version or 0)
        insert_statement = sqlite_insert(models.RunningGoal).values(
            user_id=user_id,
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
                raise Conflict("跑量目標已被更新，請重新載入後再編輯")
        except Exception:
            raise
        return goal_service.goal_values(db, user_id)
