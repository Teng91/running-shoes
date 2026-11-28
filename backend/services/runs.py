"""User-scoped runs application mutations and transaction ownership."""

from datetime import date

from sqlalchemy.orm import Session

from backend import models, schemas
from backend.clock import local_today
from backend.read_models.account_clock import account_zone
from backend.run_metrics import DEFAULT_ACTIVITY_TYPE, is_plausible_duration, pace_range_text
from backend.services.errors import Conflict, Invalid, NotFound, Unprocessable
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


def reject_future_run_date(db: Session, user_id: int, value: str) -> None:
    """SPEC-147: a run is dated on or before today on the account's own calendar."""
    zone = account_zone(db, user_id)
    today = local_today(zone)
    if date.fromisoformat(value) > today:
        raise Unprocessable(f"跑步日期不能晚於今天（{zone.key}：{today.isoformat()}）")


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
        reject_future_run_date(db, user_id, payload.date)
        run_count = db.query(models.Run).filter(models.Run.user_id == user_id).count()
        if run_count >= max_runs:
            raise Conflict("跑步紀錄已達上限")
        run = models.Run(**payload.model_dump(), user_id=user_id, id=allocate_id(db, "runs"))
        db.add(run)
        apply_run_mileage_deltas(
            db, user_id, [(payload.shoe_id, payload.date, payload.km, payload.activity_type)], 1
        )
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
        if "date" in update_data:
            reject_future_run_date(db, user_id, update_data["date"])
        # The schema checks a duration against a submitted distance; these cover the stored
        # side. SPEC-093: a distance edit must also keep a stored moving time plausible.
        stored_type = getattr(run, "activity_type", DEFAULT_ACTIVITY_TYPE)
        _check_effective_pace(run, update_data, stored_type)
        old_values = (run.shoe_id, run.date, run.km, stored_type)
        new_values = (
            int(update_data.get("shoe_id", run.shoe_id)),
            str(update_data.get("date", run.date)),
            float(update_data.get("km", run.km)),
            str(update_data.get("activity_type", stored_type)),
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
            db, user_id, [(old_values[0], old_values[1], -old_values[2], old_values[3]), new_values], 1
        )
        return run


def _check_effective_pace(run: models.Run, update_data: dict, stored_type: str) -> None:
    """The edited run's moving time, distance and type must still give a plausible pace.

    The schema checks only the submitted fields; this covers the stored side (SPEC-093) and
    the type's own bound, since hikes and walks allow a slower pace (SPEC-139).
    """
    if not {"km", "duration_seconds", "activity_type"} & update_data.keys():
        return
    activity_type = str(update_data.get("activity_type", stored_type))
    km = float(update_data.get("km", run.km))
    duration = update_data.get("duration_seconds", getattr(run, "duration_seconds", None))
    if duration is None or is_plausible_duration(duration, km, activity_type):
        return
    limit = pace_range_text(activity_type)
    if "duration_seconds" in update_data:
        raise Invalid(f"跑步時間與距離換算的配速不合理（{limit}）")
    if "km" in update_data:
        raise Invalid(f"新距離與已記錄的跑步時間換算的配速不合理（{limit}），請一併修改或清除跑步時間")
    raise Invalid(f"已記錄的跑步時間以這個運動類型換算的配速不合理（{limit}），請一併修改或清除跑步時間")


def delete_run(db: Session, user_id: int, run_id: int, expected_version: int | None = None):
    with write_transaction(db, user_id, reason="run.delete"):
        run = (
            db.query(models.Run)
            .filter(models.Run.id == run_id, models.Run.user_id == user_id)
            .first()
        )
        if not run:
            raise NotFound("Run not found")
        run_values = (run.shoe_id, run.date, run.km, getattr(run, "activity_type", DEFAULT_ACTIVITY_TYPE))
        strava_id = getattr(run, "strava_id", None)
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
        record_tombstone(db, user_id, run_id, strava_id)
        apply_run_mileage_deltas(db, user_id, [run_values], -1)
        return {"ok": True}
