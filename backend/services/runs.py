"""User-scoped runs application mutations and transaction ownership."""

from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.errors import Conflict, NotFound
from backend.services.identifiers import allocate_id
from backend.services.mileage import apply_run_mileage_deltas
from backend.services.run_identity import record_tombstone
from backend.services.transactions import write_transaction


def _user_shoe_or_404(db: Session, user_id: int, shoe_id: int):
    shoe = (
        db.query(models.Shoe)
        .filter(
            models.Shoe.id == shoe_id,
            models.Shoe.user_id == user_id,
            models.Shoe.is_deleted.is_(False),
        )
        .first()
    )
    if not shoe:
        raise NotFound("Shoe not found")
    return shoe


def create_run(
    db: Session,
    user_id: int,
    payload: schemas.RunCreate,
    *,
    max_runs: int,
):
    # Keyed retries are answered by the caller's MutationReceipt (operations.py)
    # inside the same transaction; this use case only owns the business rules.
    with write_transaction(db, user_id, reason="run.create"):
        _user_shoe_or_404(db, user_id, payload.shoe_id)
        run_count = db.query(models.Run).filter(models.Run.user_id == user_id).count()
        if isinstance(run_count, int) and run_count >= max_runs:
            raise Conflict("跑步紀錄已達上限")
        run = models.Run(**payload.model_dump(), user_id=user_id, id=allocate_id(db, "runs"))
        db.add(run)
        apply_run_mileage_deltas(db, user_id, [(payload.shoe_id, payload.date, payload.km)], 1)
        return run


def update_run(db: Session, user_id: int, run_id: int, payload: schemas.RunUpdate):
    with write_transaction(db, user_id, reason="run.update"):
        run = (
            db.query(models.Run)
            .filter(models.Run.id == run_id, models.Run.user_id == user_id)
            .first()
        )
        if not run:
            raise NotFound("Run not found")
        update_data = payload.model_dump(exclude_unset=True)
        expected_version = update_data.pop("expected_version", getattr(run, "version", 0))
        if "shoe_id" in update_data:
            _user_shoe_or_404(db, user_id, update_data["shoe_id"])
        old_values = (run.shoe_id, run.date, run.km)
        new_values = (
            int(update_data.get("shoe_id", run.shoe_id)),
            str(update_data.get("date", run.date)),
            float(update_data.get("km", run.km)),
        )
        changed = (
            db.query(models.Run)
            .filter(
                models.Run.id == run_id,
                models.Run.user_id == user_id,
                models.Run.version == expected_version,
            )
            .update(
                {
                    **{getattr(models.Run, key): value for key, value in update_data.items()},
                    models.Run.version: models.Run.version + 1,
                },
                synchronize_session=False,
            )
        )
        if not changed:
            raise Conflict("跑步紀錄已被更新，請重新載入後再編輯")
        apply_run_mileage_deltas(
            db, user_id, [(old_values[0], old_values[1], -old_values[2]), new_values], 1
        )
        return run


def delete_run(db: Session, user_id: int, run_id: int, expected_version: int | None = None):
    with write_transaction(db, user_id, reason="run.delete"):
        run = (
            db.query(models.Run)
            .filter(models.Run.id == run_id, models.Run.user_id == user_id)
            .first()
        )
        if not run:
            raise NotFound("Run not found")
        run_values = (run.shoe_id, run.date, run.km)
        version = getattr(run, "version", 0) if expected_version is None else expected_version
        changed = (
            db.query(models.Run)
            .filter(
                models.Run.id == run_id,
                models.Run.user_id == user_id,
                models.Run.version == version,
            )
            .delete(synchronize_session=False)
        )
        if not changed:
            raise Conflict("跑步紀錄已被更新，請重新載入後再刪除")
        record_tombstone(db, user_id, run_id)
        apply_run_mileage_deltas(db, user_id, [run_values], -1)
        return {"ok": True}
