"""User-scoped generation reservations and conditional report persistence."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.models import MonthlyReport, ReportGeneration
from backend.services.transactions import write_transaction


def begin_generation(db: Session, user_id: int, year: int, month: int) -> str:
    token = str(uuid4())
    with write_transaction(db, user_id):
        statement = sqlite_insert(ReportGeneration).values(
            user_id=user_id, year=year, month=month, token=token
        )
        db.execute(statement.on_conflict_do_update(
            index_elements=["user_id", "year", "month"], set_={"token": token}
        ))
    return token


def persist_current_report(
    db: Session, user_id: int, year: int, month: int, token: str,
    content: str, model: str, stats: dict,
) -> datetime | None:
    """Reserve the writer before checking ownership and upserting the snapshot."""
    with write_transaction(db, user_id):
        current = db.query(ReportGeneration.token).filter_by(
            user_id=user_id, year=year, month=month
        ).scalar()
        if current != token:
            return None
        now = datetime.now(UTC)
        statement = sqlite_insert(MonthlyReport).values(
            user_id=user_id, year=year, month=month, content_md=content,
            model=model, stats_json=stats, created_at=now, updated_at=now,
        )
        db.execute(statement.on_conflict_do_update(
            index_elements=["user_id", "year", "month"],
            set_={"content_md": content, "model": model, "stats_json": stats, "updated_at": now},
        ))
    return now
