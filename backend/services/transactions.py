"""SQLite writer reservation shared by user-owned application mutations."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.models import User


def reserve_user_write(db: Session, user_id: int) -> None:
    # An actual SQL write starts the SQLite transaction before any business read.
    # The value does not change: existing tokens and user data remain valid.
    db.execute(update(User).where(User.id == user_id).values(token_version=User.token_version))
    # Request authentication or another adapter may already have read an ORM row.
    # Read the business snapshot again only after the writer reservation is held.
    db.expire_all()


@contextmanager
def write_transaction(db: Session, user_id: int) -> Iterator[None]:
    try:
        reserve_user_write(db, user_id)
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise
