"""Monotonic identifiers prevent stale forms from editing a reused deleted ID."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend import models


def allocate_id(db: Session, entity: str) -> int:
    model: Any = {"runs": models.Run, "monthly_mileages": models.MonthlyMileage}[entity]
    # Only PK allocator metadata is global: no user record values are read or exposed.
    floor = select(func.coalesce(func.max(model.id), 0) + 1).scalar_subquery()
    statement = sqlite_insert(models.EntitySequence).values(name=entity, next_id=floor + 1)
    value = db.execute(statement.on_conflict_do_update(
        index_elements=["name"],
        set_={"next_id": func.max(models.EntitySequence.next_id, floor) + 1},
    ).returning(models.EntitySequence.next_id)).scalar_one()
    return int(value) - 1
