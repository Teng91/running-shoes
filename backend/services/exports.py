"""Framework-independent account and shoe export builders."""

import csv
import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend import models
from backend.exporting import export_filename, generate_shoe_rows


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
) -> tuple[dict[str, Any], str]:
    """Build a user-scoped account backup without credentials or secrets."""
    exported_at = now or datetime.now(UTC)
    shoes = db.query(models.Shoe).filter(models.Shoe.user_id == user.id).all()
    runs = db.query(models.Run).filter(models.Run.user_id == user.id).all()
    months = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == user.id
    ).all()
    reports = db.query(models.MonthlyReport).filter(
        models.MonthlyReport.user_id == user.id
    ).all()
    imports = db.query(models.StravaImport).filter(
        models.StravaImport.user_id == user.id
    ).all()
    goal = db.query(models.RunningGoal).filter(
        models.RunningGoal.user_id == user.id
    ).first()
    payload = {
        "format": "running-shoes-account-backup",
        "version": 1,
        "exported_at": exported_at.isoformat(),
        "username": user.username,
        "shoes": [_serialize_shoe(shoe) for shoe in shoes],
        "runs": [_serialize_run(run) for run in runs],
        "monthly_mileages": [_serialize_month(row) for row in months],
        "running_goal": _serialize_goal(goal),
        "monthly_reports": [_serialize_report(row) for row in reports],
        "strava_imports": [_serialize_strava_import(row) for row in imports],
    }
    filename = f"running_shoes_account_{exported_at.astimezone():%Y%m%d_%H%M%S}.json"
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
        "id": shoe.id, "brand": shoe.brand, "model": shoe.model, "date": shoe.date,
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
    }


def _serialize_month(row: models.MonthlyMileage) -> dict[str, Any]:
    return {
        "year": row.year, "month": row.month, "km": row.km,
        "adjustment_km": row.adjustment_km,
    }


def _serialize_goal(goal: models.RunningGoal | None) -> dict[str, Any] | None:
    if goal is None:
        return None
    return {
        "start_year": goal.start_year,
        "monthly_km": goal.monthly_km,
        "yearly_km": goal.yearly_km,
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
