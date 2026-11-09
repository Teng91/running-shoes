"""SQLite writer reservation shared by application mutations."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import delete, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.models import User, WriteContext
from backend.services.retention import prune_account_history


def reserve_user_write(db: Session, user_id: int | None) -> None:
    # An actual SQL write starts the SQLite transaction before any business read.
    # The value does not change: existing tokens and user data remain valid.
    # Registration has no user yet. The NULL primary-key predicate matches no
    # rows, but SQLite still reserves its writer before the capacity check.
    db.execute(update(User).where(User.id == user_id).values(token_version=User.token_version))
    # Request authentication or another adapter may already have read an ORM row.
    # Read the business snapshot again only after the writer reservation is held.
    db.expire_all()


@contextmanager
def write_transaction(
    db: Session, user_id: int | None = None, *, reason: str = "application.write",
    operation_id: str | None = None,
) -> Iterator[None]:
    owner = db.info.get("application_transaction")
    if owner is not None:
        if owner != user_id:
            raise RuntimeError("Nested transaction cannot change user scope")
        yield
        return
    try:
        reserve_user_write(db, user_id)
        db.info["application_transaction"] = user_id
        if user_id is not None:
            statement = sqlite_insert(WriteContext).values(
                user_id=user_id, operation_id=operation_id or str(uuid4()), reason=reason
            )
            db.execute(statement.on_conflict_do_update(
                index_elements=["user_id"], set_={
                    "operation_id": statement.excluded.operation_id, "reason": reason,
                },
            ))
        yield
        db.flush()
        if user_id is not None:
            prune_account_history(db, user_id)
            db.execute(delete(WriteContext).where(WriteContext.user_id == user_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.info.pop("application_transaction", None)
