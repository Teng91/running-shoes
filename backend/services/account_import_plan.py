"""User-scoped source matching shared by import previews and execution."""

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from backend import models
from backend.backup_contract import AccountBackup, BackupImport, backup_fingerprint
from backend.services.account_import_changes import ImportChanges, build_changes
from backend.services.errors import Conflict
from backend.services.fingerprints import payload_hash
from backend.services.run_identity import add_local_tombstones
from backend.settings import Settings

RestoreMode = Literal["merge", "update"]


@dataclass
class ImportPlan:
    user_id: int
    source: str
    mappings: dict[tuple[str, str], int]
    shoes: dict[int, models.Shoe]
    runs: dict[int, models.Run]
    months: dict[tuple[int, int], models.MonthlyMileage]
    reports: dict[tuple[int, int], models.MonthlyReport]
    goal: models.RunningGoal | None
    import_count: int
    run_targets: dict[int, int | None]
    changes: ImportChanges = field(default_factory=ImportChanges)

    def existing(self, entity: str, key: str | int) -> int | None:
        return self.mappings.get((entity, str(key)))


def build_import_plan(db: Session, uid: int, backup: AccountBackup, mode: RestoreMode) -> ImportPlan:  # noqa: C901
    source = backup.source_id or "legacy:" + backup_fingerprint(backup)
    shoes = {row.id: row for row in db.query(models.Shoe).filter_by(user_id=uid).all()}
    runs = {row.id: row for row in db.query(models.Run).filter_by(user_id=uid).all()}
    imports = db.query(models.StravaImport).filter_by(user_id=uid).all()
    mappings = {(row.entity, row.source_key): row.target_id for row in db.query(models.RestoreMapping).filter_by(user_id=uid, source_id=source).all()}
    if source == db.query(models.User.backup_id).filter_by(id=uid).scalar():
        add_local_tombstones(db, uid, mappings)
        for name, identifiers in (("shoe", shoes), ("run", runs)):
            for identifier in identifiers:
                mappings.setdefault((name, str(identifier)), identifier)
        for (identifier,) in db.query(models.AuditEvent.id).filter_by(user_id=uid).all():
            mappings.setdefault(("history", str(identifier)), identifier)
        for row in imports:
            import_item = BackupImport.model_validate({name: getattr(row, name) for name in BackupImport.model_fields})
            mappings.setdefault(("import", payload_hash(import_item.model_dump(mode="json"))), row.id)
    strava = {row.strava_id: row.id for row in runs.values() if row.strava_id}
    targets = {}
    claimed: set[int] = set()
    for item in backup.runs:
        candidates = {mappings[("run", str(key))] for key in [item.id, *item.aliases]
                      if ("run", str(key)) in mappings}
        if len(candidates) > 1:
            raise Conflict("跑步來源別名對應不同紀錄，請先核對資料；不會自動合併")
        target = next(iter(candidates), None)
        if target is None and item.strava_id:
            target = strava.get(item.strava_id)
        if mode == "update" and target is not None and target in runs:
            if target in claimed:
                raise Conflict("多筆來源跑步對應同一筆 Strava 活動，請先核對資料")
            if item.strava_id and strava.get(item.strava_id, target) != target:
                raise Conflict("Strava 活動已對應其他跑步，請先核對資料")
            claimed.add(target)
        targets[item.id] = target
    plan = ImportPlan(uid, source, mappings, shoes, runs,
                      {(row.year, row.month): row for row in db.query(models.MonthlyMileage).filter_by(user_id=uid).all()},
                      {(row.year, row.month): row for row in db.query(models.MonthlyReport).filter_by(user_id=uid).all()},
                      db.query(models.RunningGoal).filter_by(user_id=uid).first(), len(imports), targets)
    if mode == "update":
        plan.changes = build_changes(plan, backup)
    return plan


def summarize_import(plan: ImportPlan, backup: AccountBackup, config: Settings, mode: RestoreMode) -> dict:
    new_shoes = [s for s in backup.shoes if plan.existing("shoe", str(s.id)) is None]
    new_runs = [row for row in backup.runs if plan.run_targets[row.id] is None]
    active = sum(not row.is_deleted for row in plan.shoes.values())
    owned_shoes = plan.shoes
    matched_shoes = [(item, owned_shoes.get(plan.existing("shoe", str(item.id)) or 0)) for item in backup.shoes]
    if mode == "update":
        active += sum(int(not item.is_deleted) - int(not row.is_deleted) for item, row in matched_shoes if row)
    if active + sum(not row.is_deleted for row in new_shoes) > config.max_shoes_per_user:
        raise Conflict("還原後跑鞋資料會超過上限")
    if len(plan.runs) + len(new_runs) > config.max_runs_per_user:
        raise Conflict("還原後跑步紀錄會超過上限")
    incoming_imports = sum(plan.existing("import", payload_hash(row.model_dump(mode="json"))) is None
                           for row in backup.strava_imports)
    available_imports = max(0, config.max_strava_import_history_per_user - plan.import_count)
    periods = plan.months.keys()
    reports = plan.reports.keys()
    return {"mode": mode, "source_username": backup.username, "exported_at": backup.exported_at.isoformat(),
            "updated_shoes": len(plan.changes.shoes),
            "updated_runs": len(plan.changes.runs),
            "updated_months": sum(period in periods for period in plan.changes.months),
            "updated_reports": len(plan.changes.reports),
            "updated_goal": bool(plan.changes.goal),
            "new_months": len((set(plan.changes.months) if mode == "update" else
                                {(row.year, row.month) for row in backup.monthly_mileages} |
                                {(int(row.date[:4]), int(row.date[5:7])) for row in new_runs}) - set(periods)),
            "new_reports": sum((row.year, row.month) not in reports for row in backup.monthly_reports),
            "new_goal": bool(backup.running_goal and not plan.goal),
            "unchanged_shoes": sum(row is not None and row.id not in plan.changes.shoes for _, row in matched_shoes) if mode == "update" else 0,
            "unchanged_runs": sum(plan.run_targets[row.id] in plan.runs and plan.run_targets[row.id] not in plan.changes.runs for row in backup.runs) if mode == "update" else 0,
            "unchanged_months": sum((row.year, row.month) in periods and (row.year, row.month) not in plan.changes.months for row in backup.monthly_mileages) if mode == "update" else 0,
            "unchanged_reports": sum((row.year, row.month) in reports and (row.year, row.month) not in plan.changes.reports for row in backup.monthly_reports) if mode == "update" else 0,
            "unchanged_goal": bool(mode == "update" and backup.running_goal and plan.goal and not plan.changes.goal),
            "preserved_deleted_runs": sum(target is not None and target not in plan.runs for target in plan.run_targets.values()),
            "new_import_summaries": min(incoming_imports, available_imports),
            "skipped_import_summaries": len(backup.strava_imports) - min(incoming_imports, available_imports),
            "new_shoes": len(new_shoes), "new_runs": len(new_runs),
            "skipped_shoes": len(backup.shoes) - len(new_shoes),
            "skipped_runs": len(backup.runs) - len(new_runs),
            "monthly_records": len(backup.monthly_mileages), "reports": len(backup.monthly_reports),
            "history_records": len(backup.history), "legacy": backup.version == 1,
            "policy": "新增並更新同來源鞋款與跑步、檔案內月份調整、目標與月報；保留額外資料及已刪除紀錄" if mode == "update"
                      else "合併新增，保留既有鞋款、紀錄、月份調整、目標與月報"}

