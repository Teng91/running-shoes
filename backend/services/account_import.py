"""Apply a validated account import plan inside its caller-owned transaction."""

from typing import Any

from sqlalchemy.orm import Session

from backend import models
from backend.backup_contract import AccountBackup
from backend.services.account_import_plan import ImportPlan
from backend.services.errors import Conflict
from backend.services.fingerprints import payload_hash
from backend.services.identifiers import allocate_id
from backend.services.mileage import apply_run_mileage_deltas
from backend.settings import Settings


def _update_fields(row: Any, values: dict) -> None:
    if not values:
        return
    for name, value in values.items():
        setattr(row, name, value)
    if hasattr(row, "version"):
        row.version += 1


def _remember(db: Session, plan: ImportPlan, entity: str, key: str | int, target: int) -> None:
    identity = (entity, str(key))
    if identity not in plan.mappings:
        db.add(models.RestoreMapping(user_id=plan.user_id, source_id=plan.source, entity=entity,
                                     source_key=str(key), target_id=target))
        plan.mappings[identity] = target


def execute_import(db: Session, uid: int, backup: AccountBackup, config: Settings, plan: ImportPlan, *, update_existing: bool = False) -> None:
    original_periods = set(plan.months)
    if update_existing:
        for identifier, values in plan.changes.shoes.items():
            _update_fields(plan.shoes[identifier], values)
    shoes = {}
    for shoe_item in backup.shoes:
        target = plan.existing("shoe", str(shoe_item.id))
        if target is None:
            data = shoe_item.model_dump(exclude={"id", "is_deleted"})
            data["mileage"] = plan.changes.new_shoe_mileages[shoe_item.id] if update_existing else shoe_item.baseline_mileage
            shoe_row = models.Shoe(user_id=uid, **data, is_deleted=shoe_item.is_deleted)
            db.add(shoe_row)
            db.flush()
            target = shoe_row.id
        elif update_existing:
            existing_shoe = plan.shoes.get(target)
            if existing_shoe is None:
                raise Conflict("來源鞋款已不存在，無法更新")
        shoes[shoe_item.id] = target
        _remember(db, plan, "shoe", shoe_item.id, target)
    deltas = []
    db.flush()
    available_shoes = {identifier for (identifier,) in db.query(models.Shoe.id).filter_by(user_id=uid).all()}
    for run_item in backup.runs:
        target = plan.run_targets[run_item.id]
        if target is None:
            shoe_id = shoes[run_item.shoe_id]
            if shoe_id not in available_shoes:
                raise Conflict("來源鞋款已有後續刪除，無法合併跑步紀錄")
            run_row = models.Run(id=allocate_id(db, "runs"), user_id=uid, shoe_id=shoe_id, date=run_item.date, km=run_item.km, strava_id=run_item.strava_id)
            db.add(run_row)
            db.flush()
            target = run_row.id
            deltas.append((shoe_id, run_item.date, run_item.km))
        elif update_existing and target in plan.runs:
            values = dict(plan.changes.runs.get(target, {}))
            if "shoe_id" in values:
                values["shoe_id"] = shoes[values["shoe_id"]]
            _update_fields(plan.runs[target], values)
            db.flush()
        for source_key in [run_item.id, *run_item.aliases]:
            _remember(db, plan, "run", source_key, target)
    if not update_existing:
        apply_run_mileage_deltas(db, uid, deltas, 1)
        db.expire_all()
    if update_existing:
        for (year, month), values in plan.changes.months.items():
            row = plan.months.get((year, month))
            if row is None:
                row = models.MonthlyMileage(id=allocate_id(db, "monthly_mileages"), user_id=uid, year=year, month=month,
                                            **values)
                db.add(row)
                plan.months[(year, month)] = row
            else:
                _update_fields(row, values)
        db.flush()
    for month_item in backup.monthly_mileages:
        key = f"{month_item.year}-{month_item.month}"
        if plan.existing("month", key) is not None and not update_existing:
            continue
        month_row = db.query(models.MonthlyMileage).filter_by(user_id=uid, year=month_item.year, month=month_item.month).first()
        if not update_existing and (month_item.year, month_item.month) not in original_periods:
            if month_row is None:
                month_row = models.MonthlyMileage(id=allocate_id(db, "monthly_mileages"), user_id=uid, year=month_item.year, month=month_item.month, km=0, adjustment_km=0)
                db.add(month_row)
                db.flush()
            month_row.km += float(month_item.adjustment_km or 0)
            month_row.adjustment_km = float(month_item.adjustment_km or 0)
        assert month_row is not None
        _remember(db, plan, "month", key, month_row.id)
    existing_goal = db.query(models.RunningGoal).filter_by(user_id=uid).first()
    if backup.running_goal and (update_existing or not existing_goal):
        goal = backup.running_goal
        if existing_goal:
            _update_fields(existing_goal, plan.changes.goal)
        else:
            db.add(models.RunningGoal(user_id=uid, start_year=goal.start_year, monthly_km=goal.monthly_km,
                                      yearly_km=round(goal.monthly_km * 12, 2), version=1))
    for report_item in backup.monthly_reports:
        report_row = db.query(models.MonthlyReport).filter_by(user_id=uid, year=report_item.year, month=report_item.month).first()
        if report_row is None:
            data = report_item.model_dump(exclude_none=True)
            db.add(models.MonthlyReport(user_id=uid, **data))
        elif update_existing:
            _update_fields(report_row, plan.changes.reports.get((report_item.year, report_item.month), {}))
        if update_existing:
            db.query(models.ReportGeneration).filter_by(user_id=uid, year=report_item.year, month=report_item.month).delete(synchronize_session=False)
    import_slots = max(0, config.max_strava_import_history_per_user - db.query(models.StravaImport).filter_by(user_id=uid).count())
    for import_item in sorted(backup.strava_imports, key=lambda row: row.imported_at.timestamp(), reverse=True):
        key = payload_hash(import_item.model_dump(mode="json"))
        if plan.existing("import", key) is None:
            if import_slots == 0:
                _remember(db, plan, "import", key, 0)  # Explicitly skipped metadata, not a business-row reference.
                continue
            import_slots -= 1
            import_row = models.StravaImport(user_id=uid, **import_item.model_dump())
            db.add(import_row)
            db.flush()
            _remember(db, plan, "import", key, import_row.id)
    for history_item in backup.history:
        if plan.existing("history", str(history_item.id)) is None:
            history_row = models.AuditEvent(user_id=uid, **history_item.model_dump(exclude={"id", "imported"}), imported=True)
            db.add(history_row)
            db.flush()
            _remember(db, plan, "history", history_item.id, history_row.id)
    db.flush()

