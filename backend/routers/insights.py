"""Analytics, account export, shoe export, and spending routes.

This module owns read-oriented insight endpoints.  Keeping the router independent
from ``backend.main`` makes the application entry point compositional and prevents
route modules from creating circular dependencies.
"""

import csv
import io
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from backend import analytics, models
from backend.auth import get_current_user
from backend.database import get_db
from backend.exporting import export_filename, generate_shoe_rows

router = APIRouter(tags=["insights"])


@router.get("/api/analytics/dashboard")
def dashboard_analytics(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return analytics.dashboard_analytics(db, current_user.id, year, month)


@router.get("/api/shoes/{shoe_id}/analytics")
def get_shoe_analytics(
    shoe_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = analytics.shoe_analytics(db, current_user.id, shoe_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Shoe not found")
    return result


@router.get("/api/export/account")
def export_account_data(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export all user-owned product records without credentials or secrets."""
    shoes = db.query(models.Shoe).filter(models.Shoe.user_id == current_user.id).all()
    runs = db.query(models.Run).filter(models.Run.user_id == current_user.id).all()
    months = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == current_user.id
    ).all()
    report_rows = db.query(models.MonthlyReport).filter(
        models.MonthlyReport.user_id == current_user.id
    ).all()
    imports = db.query(models.StravaImport).filter(
        models.StravaImport.user_id == current_user.id
    ).all()
    goal = db.query(models.RunningGoal).filter(
        models.RunningGoal.user_id == current_user.id
    ).first()
    payload = {
        "format": "running-shoes-account-backup",
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "username": current_user.username,
        "shoes": [
            {
                "id": shoe.id,
                "brand": shoe.brand,
                "model": shoe.model,
                "date": shoe.date,
                "size": shoe.size,
                "price": shoe.price,
                "orig_price": shoe.orig_price,
                "mileage": shoe.mileage,
                "baseline_mileage": shoe.baseline_mileage,
                "expected_mileage": shoe.expected_mileage,
                "monthly_km": shoe.monthly_km,
                "is_retired": shoe.is_retired,
                "is_deleted": shoe.is_deleted,
                "categories": shoe.categories,
            }
            for shoe in shoes
        ],
        "runs": [
            {
                "id": run.id,
                "shoe_id": run.shoe_id,
                "date": run.date,
                "km": run.km,
                "strava_id": run.strava_id,
            }
            for run in runs
        ],
        "monthly_mileages": [
            {
                "year": row.year,
                "month": row.month,
                "km": row.km,
                "adjustment_km": row.adjustment_km,
            }
            for row in months
        ],
        "running_goal": (
            {
                "start_year": goal.start_year,
                "monthly_km": goal.monthly_km,
                "yearly_km": goal.yearly_km,
            }
            if goal
            else None
        ),
        "monthly_reports": [
            {
                "year": row.year,
                "month": row.month,
                "content_md": row.content_md,
                "model": row.model,
                "stats_json": row.stats_json,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in report_rows
        ],
        "strava_imports": [
            {
                "imported_at": row.imported_at.isoformat() if row.imported_at else None,
                "start_date": row.start_date,
                "end_date": row.end_date,
                "imported_count": row.imported_count,
                "imported_km": row.imported_km,
                "duplicate_count": row.duplicate_count,
                "unmapped_count": row.unmapped_count,
                "invalid_count": row.invalid_count,
            }
            for row in imports
        ],
    }
    filename = f"running_shoes_account_{datetime.now().astimezone():%Y%m%d_%H%M%S}.json"
    return JSONResponse(
        payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


RowGenerator = Callable[..., Iterable[dict[str, Any]]]
FilenameFactory = Callable[[str, str], str]


def build_shoe_export(
    format: str,
    mode: str,
    current_user: models.User,
    db: Session,
    *,
    row_generator: RowGenerator = generate_shoe_rows,
    filename_factory: FilenameFactory = export_filename,
):
    """Build a CSV/XLSX response separately from FastAPI dependency wiring."""
    query = db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    )
    if mode == "active":
        query = query.filter(models.Shoe.is_retired == False)  # noqa: E712
    elif mode == "retired":
        query = query.filter(models.Shoe.is_retired == True)  # noqa: E712
    shoes = query.order_by(models.Shoe.is_retired, models.Shoe.date.desc()).all()

    if not shoes:
        raise HTTPException(status_code=404, detail="沒有可匯出的跑鞋資料")

    include_status = mode != "retired"
    rows = list(row_generator(shoes, include_retired_status=include_status))

    if format == "csv":
        csv_output = io.StringIO()
        if rows:
            writer = csv.DictWriter(csv_output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        return StreamingResponse(
            io.BytesIO(csv_output.getvalue().encode("utf-8-sig")),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename_factory("csv", mode)}"'
                )
            },
        )

    if format == "xlsx":
        try:
            import openpyxl
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail="伺服器缺少 openpyxl 套件，無法匯出 XLSX",
            ) from exc

        wb = openpyxl.Workbook()
        ws = wb.active
        if ws is None:
            raise RuntimeError("openpyxl did not create an active worksheet")
        ws.title = "跑鞋資料"

        if rows:
            headers = list(rows[0].keys())
            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill(
                start_color="3B82F6",
                end_color="3B82F6",
                fill_type="solid",
            )
            header_alignment = Alignment(horizontal="center")

            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment

            for row_idx, row in enumerate(rows, 2):
                for col_idx, header in enumerate(headers, 1):
                    ws.cell(row=row_idx, column=col_idx, value=row[header])

            for col_idx in range(1, len(headers) + 1):
                ws.column_dimensions[get_column_letter(col_idx)].width = 18

        xlsx_output = io.BytesIO()
        wb.save(xlsx_output)
        xlsx_output.seek(0)

        return StreamingResponse(
            xlsx_output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename_factory("xlsx", mode)}"'
                )
            },
        )

    return None


@router.get("/api/export")
def export_shoes(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    mode: str = Query("active", pattern="^(all|active|retired)$"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """匯出跑鞋資料為 CSV 或 XLSX。"""
    return build_shoe_export(format, mode, current_user, db)


@router.get("/api/spending/monthly")
def monthly_spending(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回傳每月鞋款支出統計（依購買日期 grouped）。"""
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).all()

    buckets: dict[tuple[int, int], dict[str, int | float]] = {}
    for shoe in shoes:
        if not shoe.date:
            continue
        try:
            year = int(shoe.date[:4])
            month = int(shoe.date[5:7])
        except (ValueError, IndexError):
            continue
        key = (year, month)
        if key not in buckets:
            buckets[key] = {
                "year": year,
                "month": month,
                "total_paid": 0.0,
                "total_orig": 0.0,
            }
        buckets[key]["total_paid"] += shoe.price
        buckets[key]["total_orig"] += shoe.orig_price or 0

    return sorted(buckets.values(), key=lambda item: (item["year"], item["month"]))
