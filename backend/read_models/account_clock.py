"""The account's calendar zone and today (SPEC-147); `backend.clock` owns the zone rules."""

from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend import clock, models


def account_zone(db: Session, user_id: int) -> ZoneInfo:
    """The saved zone of this account; an unknown account or name uses the default zone."""
    name = db.query(models.User.timezone).filter(models.User.id == user_id).scalar()
    return clock.zone(name)


def account_today(db: Session, user_id: int) -> date:
    """Today on this account's calendar, for adapters that hold only the user id."""
    return clock.local_today(account_zone(db, user_id))
