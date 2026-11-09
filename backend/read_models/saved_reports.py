"""User-scoped saved monthly reports, independent of transport."""

from datetime import datetime

from sqlalchemy.orm import Session

from backend import models
from backend.schemas import serialize_utc_timestamp


def _timestamp(value: datetime | None) -> str | None:
    return serialize_utc_timestamp(value) if value else None


def list_saved_reports(db: Session, user_id: int) -> list[dict]:
    """Report summaries, newest month first; the Markdown body is not included."""
    rows = (
        db.query(models.MonthlyReport)
        .filter(models.MonthlyReport.user_id == user_id)
        .order_by(models.MonthlyReport.year.desc(), models.MonthlyReport.month.desc())
        .all()
    )
    return [
        {"id": row.id, "year": row.year, "month": row.month, "model": row.model,
         "updated_at": _timestamp(row.updated_at)}
        for row in rows
    ]


def saved_report(db: Session, user_id: int, year: int, month: int) -> dict | None:
    row = (
        db.query(models.MonthlyReport)
        .filter(
            models.MonthlyReport.user_id == user_id,
            models.MonthlyReport.year == year,
            models.MonthlyReport.month == month,
        )
        .first()
    )
    if row is None:
        return None
    return {
        "id": row.id, "year": row.year, "month": row.month, "model": row.model,
        "content_md": row.content_md, "stats_json": row.stats_json,
        "created_at": _timestamp(row.created_at), "updated_at": _timestamp(row.updated_at),
    }
