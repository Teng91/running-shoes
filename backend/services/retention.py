"""Bounded per-account history so one account cannot grow the database without limit.

Runs inside the caller's write transaction after its own changes, so pruning is
atomic with the mutation that produced the new rows.
"""

from typing import Any

from sqlalchemy.orm import Session

from backend import models

# Newest rows kept per account. Older audit events can no longer be shown or
# recovered; receipts far beyond any realistic offline-queue replay are dropped.
AUDIT_EVENTS_PER_USER = 5_000
MUTATION_RECEIPTS_PER_USER = 1_000
RUN_TOMBSTONES_PER_USER = 50_000


def _keep_newest(db: Session, model: Any, order_column: Any, user_id: int, keep: int) -> int:
    cutoff = (
        db.query(order_column)
        .filter(model.user_id == user_id)
        .order_by(order_column.desc())
        .offset(keep)
        .limit(1)
        .scalar()
    )
    if cutoff is None:
        return 0
    return int(
        db.query(model)
        .filter(model.user_id == user_id, order_column <= cutoff)
        .delete(synchronize_session=False)
    )


def prune_account_history(
    db: Session,
    user_id: int,
    *,
    audit_events: int = AUDIT_EVENTS_PER_USER,
    receipts: int = MUTATION_RECEIPTS_PER_USER,
    tombstones: int = RUN_TOMBSTONES_PER_USER,
) -> None:
    """Delete only this account's rows beyond each cap (oldest first)."""
    _keep_newest(db, models.AuditEvent, models.AuditEvent.id, user_id, audit_events)
    _keep_newest(db, models.MutationReceipt, models.MutationReceipt.recorded_at, user_id, receipts)
    _keep_newest(db, models.RunTombstone, models.RunTombstone.run_id, user_id, tombstones)
