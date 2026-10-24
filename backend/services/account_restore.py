"""Validated, previewed account merges with stable source mappings and receipts."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models
from backend.backup_contract import AccountBackup, BackupImport, backup_fingerprint, parse_backup
from backend.services.errors import Conflict, Invalid
from backend.services.identifiers import allocate_id
from backend.services.mileage import apply_run_mileage_deltas
from backend.services.run_requests import payload_hash
from backend.services.transactions import write_transaction
from backend.settings import Settings

RestoreMode = Literal["merge", "update"]


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


def _summary(db: Session, uid: int, backup: AccountBackup, config: Settings, mode: RestoreMode = "merge") -> dict:
    source = _source(backup)
    new_shoes = [s for s in backup.shoes if _existing(db, uid, source, "shoe", str(s.id)) is None]
    strava = {value for (value,) in db.query(models.Run.strava_id).filter_by(user_id=uid).all() if value}
    new_runs = [r for r in backup.runs if _existing(db, uid, source, "run", str(r.id)) is None
                and not (r.strava_id and r.strava_id in strava)]
    active = db.query(models.Shoe).filter_by(user_id=uid, is_deleted=False).count()
    owned_shoes = {row.id: row for row in db.query(models.Shoe).filter_by(user_id=uid).all()}
    matched_shoes = [(item, owned_shoes.get(_existing(db, uid, source, "shoe", str(item.id)) or 0)) for item in backup.shoes]
    if mode == "update":
        active += sum(int(not item.is_deleted) - int(not row.is_deleted) for item, row in matched_shoes if row)
    if active + sum(not row.is_deleted for row in new_shoes) > config.max_shoes_per_user:
        raise Conflict("還原後跑鞋資料會超過上限")
    if db.query(models.Run).filter_by(user_id=uid).count() + len(new_runs) > config.max_runs_per_user:
        raise Conflict("還原後跑步紀錄會超過上限")
    incoming_imports = sum(_existing(db, uid, source, "import", payload_hash(row.model_dump(mode="json"))) is None
                           for row in backup.strava_imports)
    available_imports = max(0, config.max_strava_import_history_per_user - db.query(models.StravaImport).filter_by(user_id=uid).count())
    periods = {(row.year, row.month) for row in db.query(models.MonthlyMileage).filter_by(user_id=uid).all()}
    reports = {(row.year, row.month) for row in db.query(models.MonthlyReport).filter_by(user_id=uid).all()}
    run_ids = {identifier for (identifier,) in db.query(models.Run.id).filter_by(user_id=uid).all()}
    return {"mode": mode, "source_username": backup.username, "exported_at": backup.exported_at.isoformat(),
            "updated_shoes": sum(row is not None for _, row in matched_shoes) if mode == "update" else 0,
            "updated_runs": sum(_existing(db, uid, source, "run", str(row.id)) in run_ids or
                                (_existing(db, uid, source, "run", str(row.id)) is None and bool(row.strava_id and row.strava_id in strava))
                                for row in backup.runs) if mode == "update" else 0,
            "updated_months": sum((row.year, row.month) in periods for row in backup.monthly_mileages) if mode == "update" else 0,
            "updated_reports": sum((row.year, row.month) in reports for row in backup.monthly_reports) if mode == "update" else 0,
            "updated_goal": bool(mode == "update" and backup.running_goal and db.query(models.RunningGoal).filter_by(user_id=uid).first()),
            "new_import_summaries": min(incoming_imports, available_imports),
            "skipped_import_summaries": len(backup.strava_imports) - min(incoming_imports, available_imports),
            "new_shoes": len(new_shoes), "new_runs": len(new_runs),
            "skipped_shoes": len(backup.shoes) - len(new_shoes),
            "skipped_runs": len(backup.runs) - len(new_runs),
            "monthly_records": len(backup.monthly_mileages), "reports": len(backup.monthly_reports),
            "history_records": len(backup.history), "legacy": backup.version == 1,
            "policy": "新增並更新同來源鞋款與跑步、檔案內月份調整、目標與月報；保留額外資料及已刪除紀錄" if mode == "update"
                      else "合併新增，保留既有鞋款、紀錄、月份調整、目標與月報"}


def preview_restore(db: Session, user_id: int, raw: bytes, config: Settings, mode: RestoreMode = "merge") -> dict:
    backup = parse_backup(raw)
    if mode not in {"merge", "update"} or (mode == "update" and backup.version != 2):
        raise Invalid("更新匯入需要 v2 帳號資料檔；舊版檔案請選擇只新增")
    with write_transaction(db, user_id, reason="account.preview"):
        db.info.pop("restore_indexes", None)
        summary = _summary(db, user_id, backup, config, mode)
        revision = db.query(models.User.data_revision).filter_by(id=user_id).scalar()
        db.query(models.RestorePreview).filter_by(user_id=user_id).delete(synchronize_session=False)
        token = str(uuid4())
        payload = {"mode": mode, "backup": backup.model_dump(mode="json")}
        db.add(models.RestorePreview(user_id=user_id, token=token, revision=revision,
                                    payload_hash=payload_hash(payload), payload_json=payload,
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
        payload = preview.payload_json
        mode = payload.get("mode", "merge")
        backup = AccountBackup.model_validate(payload.get("backup", payload))
        fingerprint_matches = payload_hash(payload) == preview.payload_hash if "backup" in payload else backup_fingerprint(backup) == preview.payload_hash
        if not fingerprint_matches or mode not in {"merge", "update"} or (mode == "update" and backup.version != 2):
            raise Conflict("還原預覽內容已變更")
        summary = _summary(db, user_id, backup, config, mode)
        _merge(db, user_id, backup, config, update_existing=mode == "update")
        response = {"ok": True, "summary": summary}
        db.add(models.MutationReceipt(user_id=user_id, operation_id=operation_id,
                                       payload_hash=fingerprint, response_json=response))
        db.delete(preview)
        return response


def _merge(db: Session, uid: int, backup: AccountBackup, config: Settings, *, update_existing: bool = False) -> None:
    source = _source(backup)
    original_periods = {(r.year, r.month) for r in db.query(models.MonthlyMileage).filter_by(user_id=uid).all()}
    owned_shoes = {row.id: row for row in db.query(models.Shoe).filter_by(user_id=uid).all()}
    owned_runs = {row.id: row for row in db.query(models.Run).filter_by(user_id=uid).all()}
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
        elif update_existing:
            existing_shoe = owned_shoes.get(target)
            if existing_shoe is None:
                raise Conflict("來源鞋款已不存在，無法更新")
            for name, value in shoe_item.model_dump(exclude={"id", "mileage"}).items():
                setattr(existing_shoe, name, value)
            existing_shoe.version += 1
        shoes[shoe_item.id] = target
        _map(db, uid, source, "shoe", shoe_item.id, target)
    deltas = []
    db.flush()
    available_shoes = {identifier for (identifier,) in db.query(models.Shoe.id).filter_by(user_id=uid).all()}
    existing_strava = {row.strava_id: row.id for row in db.query(models.Run).filter_by(user_id=uid).all() if row.strava_id}
    if update_existing:
        matched_targets: set[int] = set()
        for item in backup.runs:
            target = _existing(db, uid, source, "run", str(item.id))
            if target is None and item.strava_id:
                target = existing_strava.get(item.strava_id)
            if target is not None and target in owned_runs:
                if target in matched_targets:
                    raise Conflict("多筆來源跑步對應同一筆 Strava 活動，請先核對資料")
                matched_targets.add(target)
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
        elif update_existing and target in owned_runs:
            if run_item.strava_id and existing_strava.get(run_item.strava_id, target) != target:
                raise Conflict("Strava 活動已對應其他跑步，請先核對資料")
            run_row = owned_runs[target]
            run_row.shoe_id = shoes[run_item.shoe_id]
            run_row.date = run_item.date
            run_row.km = run_item.km
            run_row.strava_id = run_item.strava_id
            run_row.version += 1
            db.flush()
            if run_item.strava_id:
                existing_strava[run_item.strava_id] = target
        _map(db, uid, source, "run", run_item.id, target)
    if not update_existing:
        apply_run_mileage_deltas(db, uid, deltas, 1)
    for month_item in backup.monthly_mileages:
        key = f"{month_item.year}-{month_item.month}"
        if _existing(db, uid, source, "month", key) is not None and not update_existing:
            continue
        month_row = db.query(models.MonthlyMileage).filter_by(user_id=uid, year=month_item.year, month=month_item.month).first()
        if update_existing or (month_item.year, month_item.month) not in original_periods:
            if month_row is None:
                month_row = models.MonthlyMileage(id=allocate_id(db, "monthly_mileages"), user_id=uid, year=month_item.year, month=month_item.month, km=0, adjustment_km=0)
                db.add(month_row)
                db.flush()
            if not update_existing:
                month_row.km += float(month_item.adjustment_km or 0)
            month_row.adjustment_km = float(month_item.adjustment_km or 0)
            month_row.version += 1
        assert month_row is not None
        _map(db, uid, source, "month", key, month_row.id)
    existing_goal = db.query(models.RunningGoal).filter_by(user_id=uid).first()
    if backup.running_goal and (update_existing or not existing_goal):
        goal = backup.running_goal
        if existing_goal:
            existing_goal.start_year = goal.start_year
            existing_goal.monthly_km = goal.monthly_km
            existing_goal.yearly_km = round(goal.monthly_km * 12, 2)
            existing_goal.version += 1
        else:
            db.add(models.RunningGoal(user_id=uid, start_year=goal.start_year, monthly_km=goal.monthly_km,
                                      yearly_km=round(goal.monthly_km * 12, 2), version=1))
    for report_item in backup.monthly_reports:
        report_row = db.query(models.MonthlyReport).filter_by(user_id=uid, year=report_item.year, month=report_item.month).first()
        if report_row is None:
            data = report_item.model_dump(exclude_none=True)
            db.add(models.MonthlyReport(user_id=uid, **data))
        elif update_existing:
            for name, value in report_item.model_dump(exclude_none=True).items():
                setattr(report_row, name, value)
        if update_existing:
            db.query(models.ReportGeneration).filter_by(user_id=uid, year=report_item.year, month=report_item.month).delete(synchronize_session=False)
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
    if update_existing:
        _recalculate_mileage(db, uid)


def _recalculate_mileage(db: Session, uid: int) -> None:
    """Keep local-only runs while replacing source baseline/adjustment values."""
    by_shoe = {shoe_id: float(km) for shoe_id, km in db.query(models.Run.shoe_id, func.sum(models.Run.km)).filter_by(user_id=uid).group_by(models.Run.shoe_id).all()}
    for shoe in db.query(models.Shoe).filter_by(user_id=uid).all():
        shoe.mileage = round(shoe.baseline_mileage + float(by_shoe.get(shoe.id, 0)), 2)
        shoe.version += 1
    periods = {(row.year, row.month): row for row in db.query(models.MonthlyMileage).filter_by(user_id=uid).all()}
    totals = {(int(year), int(month)): float(km) for year, month, km in db.query(
        func.substr(models.Run.date, 1, 4), func.substr(models.Run.date, 6, 2), func.sum(models.Run.km),
    ).filter_by(user_id=uid).group_by(func.substr(models.Run.date, 1, 7)).all()}
    for period in periods.keys() | totals.keys():
        row = periods.get(period)
        if row is None:
            row = models.MonthlyMileage(id=allocate_id(db, "monthly_mileages"), user_id=uid, year=period[0], month=period[1], adjustment_km=0)
            db.add(row)
        row.km = round(float(row.adjustment_km or 0) + totals.get(period, 0), 2)
        row.version = (row.version or 0) + 1
    db.flush()
