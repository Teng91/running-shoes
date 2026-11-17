"""User-scoped target-race writes with optimistic concurrency (SPEC-065)."""

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.read_models.race_readiness import race_goal_values
from backend.services.errors import Conflict
from backend.services.transactions import write_transaction


def save_race_goal(db: Session, user_id: int, payload: schemas.RaceGoalUpdate) -> dict:
    with write_transaction(db, user_id, reason="race_goal.update"):
        values = payload.model_dump()
        expected_version = values.pop("expected_version", None)
        if expected_version is None:
            current = db.query(models.RaceGoal.version).filter(models.RaceGoal.user_id == user_id).scalar()
            expected_version = int(current or 0)
        insert_statement = sqlite_insert(models.RaceGoal).values(user_id=user_id, version=1, **values)
        statement = insert_statement.on_conflict_do_update(
            index_elements=["user_id"],
            set_={**values, "version": models.RaceGoal.version + 1},
            where=models.RaceGoal.version == expected_version,
        ).returning(models.RaceGoal.id)
        if db.execute(statement).scalar_one_or_none() is None:
            raise Conflict("比賽目標已被更新，請重新載入後再編輯")
        goal = race_goal_values(db, user_id)
        if goal is None:
            raise Conflict("比賽目標已被更新，請重新載入後再編輯")
        return goal


def delete_race_goal(db: Session, user_id: int, expected_version: int | None) -> None:
    with write_transaction(db, user_id, reason="race_goal.delete"):
        query = db.query(models.RaceGoal).filter(models.RaceGoal.user_id == user_id)
        if expected_version is not None:
            query = query.filter(models.RaceGoal.version == expected_version)
        if query.delete(synchronize_session=False) == 0 and expected_version is not None:
            raise Conflict("比賽目標已被更新，請重新載入後再編輯")
