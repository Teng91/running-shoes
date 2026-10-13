"""Per-user running goals and deterministic progress calculations."""

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models

DEFAULT_GOAL_START_YEAR = 2026
DEFAULT_MONTHLY_GOAL_KM = 125.0
DEFAULT_YEARLY_GOAL_KM = 1500.0


def goal_values(db: Session, user_id: int) -> dict:
    row = (
        db.query(models.RunningGoal)
        .filter(models.RunningGoal.user_id == user_id)
        .first()
    )
    return {
        "version": row.version if row else 0,
        "start_year": row.start_year if row else DEFAULT_GOAL_START_YEAR,
        "monthly_km": float(row.monthly_km if row else DEFAULT_MONTHLY_GOAL_KM),
        # The annual target is intentionally derived so monthly and annual
        # targets can never drift apart.
        "yearly_km": float(row.monthly_km if row else DEFAULT_MONTHLY_GOAL_KM) * 12,
    }


def goal_progress(
    db: Session,
    user_id: int,
    year: int,
    month: int,
    *,
    as_of: date | None = None,
) -> dict:
    """Return goal progress through the requested report month."""
    goal = goal_values(db, user_id)
    active = year >= goal["start_year"]
    today = as_of or datetime.now(timezone(timedelta(hours=8))).date()
    selected = (year, month)
    current = (today.year, today.month)
    month_prefix = f"{year:04d}-{month:02d}-"
    month_query = (
        db.query(func.sum(models.Run.km))
        .filter(
            models.Run.user_id == user_id,
            models.Run.date.like(month_prefix + "%"),
        )
    )
    if selected == current:
        month_query = month_query.filter(models.Run.date <= today.isoformat())
    elif selected > current:
        month_query = month_query.filter(models.Run.id < 0)
    month_km = round(float(month_query.scalar() or 0), 2)

    ytd_end = (
        today.isoformat()
        if selected >= current
        else f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"
    )
    ytd_value = (
        db.query(func.sum(models.Run.km))
        .filter(
            models.Run.user_id == user_id,
            models.Run.date >= f"{year:04d}-01-01",
            models.Run.date <= ytd_end,
        )
        .scalar()
    )
    ytd_km = round(float(ytd_value or 0), 2)
    monthly_goal = goal["monthly_km"]
    yearly_goal = goal["yearly_km"]
    days_in_month = monthrange(year, month)[1]
    if not active:
        month_state = "before_goal"
        elapsed_days = 0
        remaining_days = 0
    elif selected < current:
        month_state = "past"
        elapsed_days = days_in_month
        remaining_days = 0
    elif selected > current:
        month_state = "future"
        elapsed_days = 0
        remaining_days = days_in_month
    else:
        month_state = "current"
        elapsed_days = today.day
        remaining_days = days_in_month - today.day
    expected_km = round(monthly_goal * elapsed_days / days_in_month, 2)
    pace_delta = round(month_km - expected_km, 2)
    month_remaining = round(max(0, monthly_goal - month_km), 2)
    return {
        **goal,
        "active": active,
        "month_km": month_km,
        "month_state": month_state,
        "days_in_month": days_in_month,
        "elapsed_days": elapsed_days,
        "remaining_days": remaining_days,
        "expected_km_to_date": expected_km,
        "pace_delta_km": pace_delta,
        "month_achievement_percent": round(month_km / monthly_goal * 100, 1),
        "month_remaining_km": month_remaining,
        "required_daily_km": (
            round(month_remaining / remaining_days, 2) if remaining_days > 0 else None
        ),
        "ytd_km": ytd_km,
        "year_achievement_percent": round(ytd_km / yearly_goal * 100, 1),
        "year_remaining_km": round(max(0, yearly_goal - ytd_km), 2),
    }
