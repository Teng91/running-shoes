"""User-scoped audit reads and conservative, mileage-aware deletion recovery."""


from typing import Any

from sqlalchemy.orm import Session

from backend import models
from backend.services.errors import Conflict, Invalid, NotFound
from backend.services.identifiers import allocate_id
from backend.services.mileage import apply_run_mileage_deltas
from backend.services.run_identity import relink_recovered_run
from backend.services.transactions import write_transaction
from backend.settings import Settings


def can_restore(event: models.AuditEvent) -> bool:
    if event.restored or event.imported or not event.before_json:
        return False
    if event.entity in {"runs", "monthly_mileages"} and event.action == "delete":
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
        data = dict(event.before_json or {})
        row: Any
        if event.entity == "runs":
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
                             version=data["version"] + 1)
            db.add(row)
            relink_recovered_run(db, user_id, event.entity_id, row.id)
            apply_run_mileage_deltas(db, user_id, [(shoe.id, row.date, row.km)], 1)
        elif event.entity == "shoes":
            row = db.query(models.Shoe).filter_by(id=event.entity_id, user_id=user_id).first()
            if row is None or not row.is_deleted or row.version != (event.after_json or {}).get("version"):
                raise Conflict("鞋款已有後續異動，請重新載入")
            count = db.query(models.Shoe).filter_by(user_id=user_id, is_deleted=False).count()
            if count >= config.max_shoes_per_user:
                raise Conflict("跑鞋資料已達上限")
            row.is_deleted = False
            row.version += 1
        elif event.entity == "monthly_mileages":
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
            else:
                if row is None or row.version != (event.after_json or {}).get("version"):
                    raise Conflict("月份已有後續異動，無法直接復原")
                row.km = data["km"]
                row.adjustment_km = data["adjustment_km"]
                row.version += 1
        else:
            raise Invalid("此類異動不支援復原")
        event.restored = True
        db.flush()
        return {"ok": True, "entity": event.entity, "id": row.id}
