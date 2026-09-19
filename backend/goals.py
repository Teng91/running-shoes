"""Per-user running goals and deterministic progress calculations."""

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
        "start_year": row.start_year if row else DEFAULT_GOAL_START_YEAR,
        "monthly_km": float(row.monthly_km if row else DEFAULT_MONTHLY_GOAL_KM),
        "yearly_km": float(row.yearly_km if row else DEFAULT_YEARLY_GOAL_KM),
    }


def goal_progress(db: Session, user_id: int, year: int, month: int) -> dict:
    """Return goal progress through the requested report month."""
    goal = goal_values(db, user_id)
    active = year >= goal["start_year"]
    month_row = (
        db.query(models.MonthlyMileage.km)
        .filter(
            models.MonthlyMileage.user_id == user_id,
            models.MonthlyMileage.year == year,
            models.MonthlyMileage.month == month,
        )
        .first()
    )
    month_km = round(float(month_row[0] if month_row else 0), 2)
    ytd_value = (
        db.query(func.sum(models.MonthlyMileage.km))
        .filter(
            models.MonthlyMileage.user_id == user_id,
            models.MonthlyMileage.year == year,
            models.MonthlyMileage.month <= month,
        )
        .scalar()
    )
    ytd_km = round(float(ytd_value or 0), 2)
    monthly_goal = goal["monthly_km"]
    yearly_goal = goal["yearly_km"]
    return {
        **goal,
        "active": active,
        "month_km": month_km,
        "month_achievement_percent": round(month_km / monthly_goal * 100, 1),
        "month_remaining_km": round(max(0, monthly_goal - month_km), 2),
        "ytd_km": ytd_km,
        "year_achievement_percent": round(ytd_km / yearly_goal * 100, 1),
        "year_remaining_km": round(max(0, yearly_goal - ytd_km), 2),
    }
