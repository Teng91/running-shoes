"""Framework-independent account and shoe export builders."""

import csv
import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend import models
from backend.backup_contract import (
    ARCHIVE_LIMITS,
    MAX_RUN_ALIASES,
    RACE_GOAL_FIELDS,
    ArchiveBudget,
    validate_export,
)
from backend.clock import APP_TIMEZONE
from backend.exporting import export_filename, generate_shoe_rows
from backend.read_models.goal_progress import yearly_goal_km
from backend.services.errors import Invalid
from backend.services.run_identity import export_run_aliases


class NoExportRowsError(Exception):
    """Raised when the authenticated user has no matching shoes to export."""


class ExportDependencyError(Exception):
    """Raised when an optional export dependency is unavailable."""


@dataclass(frozen=True)
class ExportFile:
    content: bytes
    media_type: str
    filename: str


RowGenerator = Callable[..., Iterable[dict[str, Any]]]
FilenameFactory = Callable[[str, str], str]


def build_account_export(
    db: Session,
    user: models.User,
    *,
    now: datetime | None = None,
    include_history: bool = True,
) -> tuple[dict[str, Any], str]:
    """Keep every collection in the same SQLite read snapshot, including legacy mode."""
    # SAVEPOINT establishes a physical transaction even when pysqlite does not
    # BEGIN for SELECT. Releasing it neither commits nor rolls back caller writes.
    with db.begin_nested():
        return _account_export_snapshot(db, user, now=now, include_history=include_history)


def _account_export_snapshot(db: Session, user: models.User, *, now: datetime | None, include_history: bool) -> tuple[dict[str, Any], str]:
    exported_at = now or datetime.now(UTC)
    budget = ArchiveBudget()
    def rows(model, collection, serialize):
        limit = ARCHIVE_LIMITS[collection]
        result: list[dict[str, Any]] = []
        query = db.query(model).filter_by(user_id=user.id).order_by(model.id).limit(limit + 1)
        for row in query.yield_per(100):
            if len(result) == limit:
                label = {"shoes": "鞋款", "runs": "跑步", "monthly_mileages": "月跑量", "monthly_reports": "月報", "strava_imports": "匯入摘要", "history": "異動歷史"}[collection]
                action = "取消包含異動歷史後再下載" if collection == "history" else "使用管理員完整資料庫備份"
                raise Invalid(f"{label}超過 JSON 備份 {limit:,} 筆上限，未產生下載檔。請{action}。")
            value = serialize(row)
            budget.add(value)
            result.append(value)
        return result
    goal = db.query(models.RunningGoal).filter(
        models.RunningGoal.user_id == user.id
    ).first()
    race_goal = db.query(models.RaceGoal).filter(models.RaceGoal.user_id == user.id).first()
    aliases = export_run_aliases(db, user.id, user.backup_id, MAX_RUN_ALIASES)
    payload = {
        "format": "running-shoes-account-backup",
        "version": 6,
        "source_id": user.backup_id,
        "exported_at": exported_at.isoformat(),
        "username": user.username,
        "shoes": rows(models.Shoe, "shoes", _serialize_shoe),
        "runs": rows(models.Run, "runs", lambda run: {**_serialize_run(run), "aliases": aliases.get(run.id, [])}),
        "monthly_mileages": rows(models.MonthlyMileage, "monthly_mileages", _serialize_month),
        "running_goal": _serialize_goal(goal),
        "race_goal": _serialize_race_goal(race_goal),
        "monthly_reports": rows(models.MonthlyReport, "monthly_reports", _serialize_report),
        "strava_imports": rows(models.StravaImport, "strava_imports", _serialize_strava_import),
        "history": rows(models.AuditEvent, "history", _serialize_history) if include_history else [],
    }
    validate_export(payload)
    suffix = "" if include_history else "_without_history"
    # Fly machines run in UTC; name the file with the application calendar time.
    filename = f"running_shoes_account_{exported_at.astimezone(APP_TIMEZONE):%Y%m%d_%H%M%S}{suffix}.json"
    return payload, filename


def build_shoe_export(
    format: str,
    mode: str,
    user_id: int,
    db: Session,
    *,
    row_generator: RowGenerator = generate_shoe_rows,
    filename_factory: FilenameFactory = export_filename,
) -> ExportFile | None:
    """Build a user-scoped CSV or XLSX export without HTTP response types."""
    query = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
    )
    if mode == "active":
        query = query.filter(models.Shoe.is_retired.is_(False))
    elif mode == "retired":
        query = query.filter(models.Shoe.is_retired.is_(True))
    shoes = query.order_by(models.Shoe.is_retired, models.Shoe.date.desc()).all()
    if not shoes:
        raise NoExportRowsError

    rows = list(row_generator(shoes, include_retired_status=mode != "retired"))
    if format == "csv":
        return _build_csv(rows, filename_factory("csv", mode))
    if format == "xlsx":
        return _build_xlsx(rows, filename_factory("xlsx", mode))
    return None


def _build_csv(rows: list[dict[str, Any]], filename: str) -> ExportFile:
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return ExportFile(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        filename=filename,
    )


def _build_xlsx(rows: list[dict[str, Any]], filename: str) -> ExportFile:
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise ExportDependencyError("伺服器缺少 openpyxl 套件，無法匯出 XLSX") from exc

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    if worksheet is None:
        raise RuntimeError("openpyxl did not create an active worksheet")
    worksheet.title = "跑鞋資料"
    if rows:
        headers = list(rows[0].keys())
        for col_idx, header in enumerate(headers, 1):
            cell = worksheet.cell(row=1, column=col_idx, value=header)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(
                start_color="3B82F6", end_color="3B82F6", fill_type="solid"
            )
            cell.alignment = Alignment(horizontal="center")
        for row_idx, row in enumerate(rows, 2):
            for col_idx, header in enumerate(headers, 1):
                worksheet.cell(row=row_idx, column=col_idx, value=row[header])
        for col_idx in range(1, len(headers) + 1):
            worksheet.column_dimensions[get_column_letter(col_idx)].width = 18

    output = io.BytesIO()
    workbook.save(output)
    return ExportFile(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


def _serialize_shoe(shoe: models.Shoe) -> dict[str, Any]:
    return {
        "id": shoe.id, "nickname": shoe.nickname, "brand": shoe.brand, "model": shoe.model, "date": shoe.date,
        "size": shoe.size, "price": shoe.price, "orig_price": shoe.orig_price,
        "mileage": shoe.mileage, "baseline_mileage": shoe.baseline_mileage,
        "expected_mileage": shoe.expected_mileage, "monthly_km": shoe.monthly_km,
        "is_retired": shoe.is_retired, "is_deleted": shoe.is_deleted,
        "categories": shoe.categories,
    }


def _serialize_run(run: models.Run) -> dict[str, Any]:
    return {
        "id": run.id, "shoe_id": run.shoe_id, "date": run.date,
        "km": run.km, "strava_id": run.strava_id,
        "duration_seconds": run.duration_seconds,
        "activity_type": run.activity_type,
    }


def _serialize_month(row: models.MonthlyMileage) -> dict[str, Any]:
    return {
        "year": row.year, "month": row.month, "km": row.km,
        "adjustment_km": row.adjustment_km,
    }


def _serialize_race_goal(goal: models.RaceGoal | None) -> dict[str, Any] | None:
    """SPEC-126: the target race without its row identity or write version."""
    if goal is None:
        return None
    return {name: getattr(goal, name) for name in RACE_GOAL_FIELDS}


def _serialize_goal(goal: models.RunningGoal | None) -> dict[str, Any] | None:
    if goal is None:
        return None
    return {
        "start_year": goal.start_year,
        "monthly_km": goal.monthly_km,
        # Derived like goal_values, so legacy rows with float artifacts export cleanly.
        "yearly_km": yearly_goal_km(goal.monthly_km),
    }


def _serialize_report(row: models.MonthlyReport) -> dict[str, Any]:
    return {
        "year": row.year, "month": row.month, "content_md": row.content_md,
        "model": row.model, "stats_json": row.stats_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_strava_import(row: models.StravaImport) -> dict[str, Any]:
    return {
        "imported_at": row.imported_at.isoformat() if row.imported_at else None,
        "start_date": row.start_date, "end_date": row.end_date,
        "imported_count": row.imported_count, "imported_km": row.imported_km,
        "duplicate_count": row.duplicate_count, "unmapped_count": row.unmapped_count,
        "invalid_count": row.invalid_count,
    }


def _serialize_history(row: models.AuditEvent) -> dict[str, Any]:
    return {key: getattr(row, key) for key in (
        "id", "operation_id", "reason", "entity", "entity_id", "action", "before_json",
        "after_json", "created_at", "restored", "imported",
    )}
