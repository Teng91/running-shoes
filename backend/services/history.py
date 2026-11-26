"""User-scoped audit reads and conservative, mileage-aware deletion recovery."""


from typing import Any

from sqlalchemy.orm import Session

from backend import models
from backend.backup_contract import RACE_GOAL_FIELDS
from backend.run_metrics import DEFAULT_ACTIVITY_TYPE
from backend.services.errors import Conflict, Invalid, NotFound
from backend.services.identifiers import allocate_id
from backend.services.mileage import apply_run_mileage_deltas
from backend.services.run_identity import relink_recovered_run
from backend.services.transactions import write_transaction
from backend.settings import Settings


def can_restore(event: models.AuditEvent) -> bool:
    if event.restored or event.imported or not event.before_json:
        return False
    if event.entity in {"runs", "monthly_mileages", "race_goals"} and event.action == "delete":
        return True
    if event.entity == "shoes":
        return bool(event.after_json and event.after_json.get("is_deleted")
                    and not event.before_json.get("is_deleted"))
    return event.entity == "monthly_mileages" and event.reason == "monthly.delete"


def list_history(db: Session, user_id: int, *, before: int | None = None, limit: int = 50) -> dict:
    query = db.query(models.AuditEvent).filter(models.AuditEvent.user_id == user_id)
    if before is not None:
        query = query.filter(models.AuditEvent.id < before)
    rows = query.order_by(models.AuditEvent.id.desc()).limit(limit + 1).all()
    return {"rows": [
        {"id": row.id, "operation_id": row.operation_id, "reason": row.reason,
         "entity": row.entity, "entity_id": row.entity_id, "action": row.action,
         "before": row.before_json, "after": row.after_json, "created_at": row.created_at,
         "restored": row.restored, "imported": row.imported, "can_restore": can_restore(row)}
        for row in rows[:limit]
    ], "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


def restore_deleted(db: Session, user_id: int, event_id: int, config: Settings) -> dict:
    with write_transaction(db, user_id, reason="history.restore"):
        event = db.query(models.AuditEvent).filter_by(id=event_id, user_id=user_id).first()
        if event is None:
            raise NotFound("找不到異動紀錄")
        if not can_restore(event):
            raise Conflict("此異動無法復原或已經復原")
        restorer = _RESTORERS.get(event.entity)
        if restorer is None:
            raise Invalid("此類異動不支援復原")
        row = restorer(db, user_id, event, dict(event.before_json or {}), config)
        event.restored = True
        db.flush()
        return {"ok": True, "entity": event.entity, "id": row.id}


def _restore_run(db: Session, user_id: int, event: models.AuditEvent, data: dict, config: Settings) -> Any:
    """A deleted run comes back on its shoe, under a new ID, with its mileage."""
    shoe = db.query(models.Shoe).filter_by(id=data["shoe_id"], user_id=user_id, is_deleted=False).first()
    if shoe is None:
        raise Conflict("原鞋款已刪除，請先復原鞋款")
    if db.query(models.Run).filter_by(user_id=user_id).count() >= config.max_runs_per_user:
        raise Conflict("跑步紀錄已達上限")
    if data.get("strava_id") and db.query(models.Run).filter_by(
        user_id=user_id, strava_id=data["strava_id"]
    ).first():
        raise Conflict("此 Strava 活動已存在")
    row = models.Run(id=allocate_id(db, "runs"), user_id=user_id, shoe_id=shoe.id, date=data["date"], km=data["km"],
                     strava_id=data.get("strava_id"), duration_seconds=data.get("duration_seconds"),
                     activity_type=data.get("activity_type") or DEFAULT_ACTIVITY_TYPE,
                     version=data["version"] + 1)
    db.add(row)
    relink_recovered_run(db, user_id, event.entity_id, row.id)
    apply_run_mileage_deltas(db, user_id, [(shoe.id, row.date, row.km, row.activity_type)], 1)
    return row


def _restore_shoe(db: Session, user_id: int, event: models.AuditEvent, data: dict, config: Settings) -> Any:
    """A soft-deleted shoe is undeleted, unless it changed after the deletion."""
    row = db.query(models.Shoe).filter_by(id=event.entity_id, user_id=user_id).first()
    if row is None or not row.is_deleted or row.version != (event.after_json or {}).get("version"):
        raise Conflict("鞋款已有後續異動，請重新載入")
    count = db.query(models.Shoe).filter_by(user_id=user_id, is_deleted=False).count()
    if count >= config.max_shoes_per_user:
        raise Conflict("跑鞋資料已達上限")
    row.is_deleted = False
    row.version += 1
    return row


def _restore_month(db: Session, user_id: int, event: models.AuditEvent, data: dict, config: Settings) -> Any:
    """A deleted month is recreated; an edited one gets its previous totals back."""
    row = db.query(models.MonthlyMileage).filter_by(
        user_id=user_id, year=data["year"], month=data["month"]
    ).first()
    if event.action == "delete":
        if row is not None:
            raise Conflict("該月份已有新紀錄，請以月跑量編輯調整")
        row = models.MonthlyMileage(id=allocate_id(db, "monthly_mileages"), user_id=user_id, year=data["year"], month=data["month"],
                                    km=data["km"], adjustment_km=data["adjustment_km"],
                                    version=data["version"] + 1)
        db.add(row)
        return row
    if row is None or row.version != (event.after_json or {}).get("version"):
        raise Conflict("月份已有後續異動，無法直接復原")
    row.km = data["km"]
    row.adjustment_km = data["adjustment_km"]
    row.version += 1
    return row


def _restore_race_goal(db: Session, user_id: int, event: models.AuditEvent, data: dict, config: Settings) -> Any:
    """SPEC-128: a deleted target race comes back, unless the account already set a new one."""
    if db.query(models.RaceGoal.id).filter_by(user_id=user_id).first() is not None:
        raise Conflict("已經有新的目標賽事，請先刪除或直接修改")
    row = models.RaceGoal(user_id=user_id, version=data["version"] + 1,
                          **{name: data.get(name) for name in RACE_GOAL_FIELDS})
    db.add(row)
    db.flush()
    return row


_RESTORERS = {"runs": _restore_run, "shoes": _restore_shoe, "monthly_mileages": _restore_month,
              "race_goals": _restore_race_goal}
