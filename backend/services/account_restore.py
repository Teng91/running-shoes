"""Validated, previewed account merges with stable source mappings and receipts."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from backend import models
from backend.backup_contract import AccountBackup, BackupImport, backup_fingerprint, parse_backup
from backend.services.errors import Conflict
from backend.services.identifiers import allocate_id
from backend.services.mileage import apply_run_mileage_deltas
from backend.services.run_requests import payload_hash
from backend.services.transactions import write_transaction
from backend.settings import Settings


def _source(backup: AccountBackup) -> str:
    return backup.source_id or "legacy:" + backup_fingerprint(backup)


def _existing(db: Session, uid: int, source: str, entity: str, key: str) -> int | None:
    cache_key = (uid, source)
    indexes = db.info.setdefault("restore_indexes", {})
    if cache_key not in indexes:
        mappings = {(row.entity, row.source_key): row.target_id for row in db.query(models.RestoreMapping).filter_by(
            user_id=uid, source_id=source
        ).all()}
        if source == db.query(models.User.backup_id).filter_by(id=uid).scalar():
            for name, model in (("shoe", models.Shoe), ("run", models.Run), ("history", models.AuditEvent)):
                for (identifier,) in db.query(model.id).filter_by(user_id=uid).all():
                    mappings.setdefault((name, str(identifier)), identifier)
            for row in db.query(models.StravaImport).filter_by(user_id=uid).all():
                item = BackupImport.model_validate({name: getattr(row, name) for name in BackupImport.model_fields})
                mappings.setdefault(("import", payload_hash(item.model_dump(mode="json"))), row.id)
        indexes[cache_key] = mappings
    return indexes[cache_key].get((entity, key))


def _map(db, uid, source, entity, key, target):
    mappings = db.info["restore_indexes"][(uid, source)]
    if (entity, str(key)) not in mappings:
        db.add(models.RestoreMapping(user_id=uid, source_id=source, entity=entity,
                                     source_key=str(key), target_id=target))
        mappings[(entity, str(key))] = target


def _summary(db: Session, uid: int, backup: AccountBackup, config: Settings) -> dict:
    source = _source(backup)
    new_shoes = [s for s in backup.shoes if _existing(db, uid, source, "shoe", str(s.id)) is None]
    strava = {value for (value,) in db.query(models.Run.strava_id).filter_by(user_id=uid).all() if value}
    new_runs = [r for r in backup.runs if _existing(db, uid, source, "run", str(r.id)) is None
                and not (r.strava_id and r.strava_id in strava)]
    active = db.query(models.Shoe).filter_by(user_id=uid, is_deleted=False).count()
    if active + sum(not row.is_deleted for row in new_shoes) > config.max_shoes_per_user:
        raise Conflict("還原後跑鞋資料會超過上限")
    if db.query(models.Run).filter_by(user_id=uid).count() + len(new_runs) > config.max_runs_per_user:
        raise Conflict("還原後跑步紀錄會超過上限")
    incoming_imports = sum(_existing(db, uid, source, "import", payload_hash(row.model_dump(mode="json"))) is None
                           for row in backup.strava_imports)
    available_imports = max(0, config.max_strava_import_history_per_user - db.query(models.StravaImport).filter_by(user_id=uid).count())
    return {"new_import_summaries": min(incoming_imports, available_imports),
            "skipped_import_summaries": len(backup.strava_imports) - min(incoming_imports, available_imports),
            "new_shoes": len(new_shoes), "new_runs": len(new_runs),
            "skipped_shoes": len(backup.shoes) - len(new_shoes),
            "skipped_runs": len(backup.runs) - len(new_runs),
            "monthly_records": len(backup.monthly_mileages), "reports": len(backup.monthly_reports),
            "history_records": len(backup.history), "legacy": backup.version == 1,
            "policy": "合併新增，保留既有鞋款、紀錄、月份調整、目標與月報"}


def preview_restore(db: Session, user_id: int, raw: bytes, config: Settings) -> dict:
    backup = parse_backup(raw)
    with write_transaction(db, user_id, reason="account.preview"):
        db.info.pop("restore_indexes", None)
        summary = _summary(db, user_id, backup, config)
        revision = db.query(models.User.data_revision).filter_by(id=user_id).scalar()
        db.query(models.RestorePreview).filter_by(user_id=user_id).delete(synchronize_session=False)
        token = str(uuid4())
        db.add(models.RestorePreview(user_id=user_id, token=token, revision=revision,
                                    payload_hash=backup_fingerprint(backup),
                                    payload_json=backup.model_dump(mode="json"),
                                    expires_at=datetime.now(UTC) + timedelta(minutes=20)))
        return {"token": token, "summary": summary, "expires_in_seconds": 1200}


def apply_restore(db: Session, user_id: int, token: str, operation_id: str, config: Settings) -> dict:
    fingerprint = payload_hash({"kind": "account.restore", "token": token})
    with write_transaction(db, user_id, reason="account.restore", operation_id=operation_id):
        db.info.pop("restore_indexes", None)
        receipt = db.get(models.MutationReceipt, (user_id, operation_id))
        if receipt is not None:
            if receipt.payload_hash != fingerprint:
                raise Conflict("操作識別碼已用於不同內容")
            return receipt.response_json
        preview = db.query(models.RestorePreview).filter_by(user_id=user_id, token=token).first()
        revision = db.query(models.User.data_revision).filter_by(id=user_id).scalar()
        if preview is None or preview.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
            raise Conflict("還原預覽已過期，請重新預覽")
        if preview.revision != revision:
            raise Conflict("資料已在預覽後變更，請重新預覽")
        backup = AccountBackup.model_validate(preview.payload_json)
        if backup_fingerprint(backup) != preview.payload_hash:
            raise Conflict("還原預覽內容已變更")
        summary = _summary(db, user_id, backup, config)
        _merge(db, user_id, backup, config)
        response = {"ok": True, "summary": summary}
        db.add(models.MutationReceipt(user_id=user_id, operation_id=operation_id,
                                       payload_hash=fingerprint, response_json=response))
        db.delete(preview)
        return response


def _merge(db: Session, uid: int, backup: AccountBackup, config: Settings) -> None:
    source = _source(backup)
    original_periods = {(r.year, r.month) for r in db.query(models.MonthlyMileage).filter_by(user_id=uid).all()}
    shoes = {}
    for shoe_item in backup.shoes:
        target = _existing(db, uid, source, "shoe", str(shoe_item.id))
        if target is None:
            data = shoe_item.model_dump(exclude={"id", "is_deleted"})
            data["mileage"] = shoe_item.baseline_mileage
            shoe_row = models.Shoe(user_id=uid, **data, is_deleted=shoe_item.is_deleted)
            db.add(shoe_row)
            db.flush()
            target = shoe_row.id
        shoes[shoe_item.id] = target
        _map(db, uid, source, "shoe", shoe_item.id, target)
    deltas = []
    available_shoes = {identifier for (identifier,) in db.query(models.Shoe.id).filter_by(user_id=uid).all()}
    existing_strava = {row.strava_id: row.id for row in db.query(models.Run).filter_by(user_id=uid).all() if row.strava_id}
    for run_item in backup.runs:
        target = _existing(db, uid, source, "run", str(run_item.id))
        if target is None and run_item.strava_id:
            target = existing_strava.get(run_item.strava_id)
        if target is None:
            shoe_id = shoes[run_item.shoe_id]
            if shoe_id not in available_shoes:
                raise Conflict("來源鞋款已有後續刪除，無法合併跑步紀錄")
            run_row = models.Run(id=allocate_id(db, "runs"), user_id=uid, shoe_id=shoe_id, date=run_item.date, km=run_item.km, strava_id=run_item.strava_id)
            db.add(run_row)
            db.flush()
            target = run_row.id
            deltas.append((shoe_id, run_item.date, run_item.km))
        _map(db, uid, source, "run", run_item.id, target)
    apply_run_mileage_deltas(db, uid, deltas, 1)
    for month_item in backup.monthly_mileages:
        key = f"{month_item.year}-{month_item.month}"
        if _existing(db, uid, source, "month", key) is not None:
            continue
        month_row = db.query(models.MonthlyMileage).filter_by(user_id=uid, year=month_item.year, month=month_item.month).first()
        if (month_item.year, month_item.month) not in original_periods:
            if month_row is None:
                month_row = models.MonthlyMileage(id=allocate_id(db, "monthly_mileages"), user_id=uid, year=month_item.year, month=month_item.month, km=0, adjustment_km=0)
                db.add(month_row)
                db.flush()
            month_row.km += float(month_item.adjustment_km or 0)
            month_row.adjustment_km = float(month_item.adjustment_km or 0)
            month_row.version += 1
        assert month_row is not None
        _map(db, uid, source, "month", key, month_row.id)
    if backup.running_goal and not db.query(models.RunningGoal).filter_by(user_id=uid).first():
        goal = backup.running_goal
        db.add(models.RunningGoal(user_id=uid, start_year=goal.start_year, monthly_km=goal.monthly_km,
                                  yearly_km=round(goal.monthly_km * 12, 2), version=1))
    for report_item in backup.monthly_reports:
        report_row = db.query(models.MonthlyReport).filter_by(user_id=uid, year=report_item.year, month=report_item.month).first()
        if report_row is None:
            data = report_item.model_dump(exclude_none=True)
            db.add(models.MonthlyReport(user_id=uid, **data))
    import_slots = max(0, config.max_strava_import_history_per_user - db.query(models.StravaImport).filter_by(user_id=uid).count())
    for import_item in sorted(backup.strava_imports, key=lambda row: row.imported_at.timestamp(), reverse=True):
        key = payload_hash(import_item.model_dump(mode="json"))
        if _existing(db, uid, source, "import", key) is None:
            if import_slots == 0:
                _map(db, uid, source, "import", key, 0)  # Explicitly skipped metadata, not a business-row reference.
                continue
            import_slots -= 1
            import_row = models.StravaImport(user_id=uid, **import_item.model_dump())
            db.add(import_row)
            db.flush()
            _map(db, uid, source, "import", key, import_row.id)
    for history_item in backup.history:
        if _existing(db, uid, source, "history", str(history_item.id)) is None:
            history_row = models.AuditEvent(user_id=uid, **history_item.model_dump(exclude={"id", "imported"}), imported=True)
            db.add(history_row)
            db.flush()
            _map(db, uid, source, "history", history_item.id, history_row.id)
    db.flush()
