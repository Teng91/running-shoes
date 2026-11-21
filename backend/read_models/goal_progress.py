"""Per-user running goals and deterministic progress calculations."""

from calendar import isleap, monthrange
from datetime import date

from sqlalchemy.orm import Session

from backend import models
from backend.clock import local_today
from backend.read_models.rounding import round_metric
from backend.read_models.run_statistics import (
    monthly_run_distances,
    period_distances,
    run_period,
)

DEFAULT_GOAL_START_YEAR = 2026
DEFAULT_MONTHLY_GOAL_KM = 125.0
DEFAULT_YEARLY_GOAL_KM = 1500.0


def yearly_goal_km(monthly_km: float) -> float:
    """The derived annual target at the stored two-decimal precision (12.3 → 147.6)."""
    return round_metric(float(monthly_km) * 12, 2)


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
        "yearly_km": yearly_goal_km(row.monthly_km if row else DEFAULT_MONTHLY_GOAL_KM),
    }


def goal_progress(
    db: Session,
    user_id: int,
    year: int,
    month: int,
    *,
    as_of: date | None = None,
    distances: dict[str, float] | None = None,
) -> dict:
    """Return goal progress through the requested report month."""
    goal = goal_values(db, user_id)
    active = year >= goal["start_year"]
    today = as_of or local_today()
    selected = (year, month)
    current = (today.year, today.month)
    totals = distances if distances is not None else period_distances(
        db, user_id, run_period(year, month, today)
    )
    month_km = totals["month_km"]
    ytd_km = totals["ytd_km"]
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
    expected_km = round_metric(monthly_goal * elapsed_days / days_in_month, 2)
    pace_delta = round_metric(month_km - expected_km, 2)
    month_remaining = round_metric(max(0, monthly_goal - month_km), 2)
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
        "month_achievement_percent": round_metric(month_km / monthly_goal * 100, 1),
        "month_remaining_km": month_remaining,
        "required_daily_km": (
            round_metric(month_remaining / remaining_days, 2) if remaining_days > 0 else None
        ),
        "ytd_km": ytd_km,
        "year_achievement_percent": round_metric(ytd_km / yearly_goal * 100, 1),
        "year_remaining_km": round_metric(max(0, yearly_goal - ytd_km), 2),
    }


def days_in_year(year: int) -> int:
    return 366 if isleap(year) else 365


def yearly_goal_to_date(yearly_km: float, year: int, elapsed_days: int) -> float:
    """Pro-rata annual target after ``elapsed_days``; trends draw the same goal line."""
    return round_metric(yearly_km * elapsed_days / days_in_year(year))


def year_goal_overview(
    db: Session, user_id: int, year: int, *, as_of: date | None = None
) -> dict:
    """Annual goal progress with every month's logged distance against the monthly target."""
    today = as_of or local_today()
    if year < today.year:
        year_state, focus_month, elapsed = "past", 12, days_in_year(year)
    elif year > today.year:
        year_state, focus_month, elapsed = "future", 1, 0
    else:
        year_state, focus_month = "current", today.month
        elapsed = (today - date(year, 1, 1)).days + 1
    progress = goal_progress(db, user_id, year, focus_month, as_of=today)
    monthly_goal = progress["monthly_km"]
    yearly_goal = progress["yearly_km"]
    current = (today.year, today.month)
    months = []
    for month, km in enumerate(monthly_run_distances(db, user_id, year, today), start=1):
        selected = (year, month)
        state = "past" if selected < current else "current" if selected == current else "future"
        months.append({
            "month": month,
            "km": km,
            "state": state,
            "percent": round_metric(km / monthly_goal * 100, 1),
            "met": progress["active"] and km >= monthly_goal,
        })
    expected = yearly_goal_to_date(yearly_goal, year, elapsed)
    remaining_days = days_in_year(year) - elapsed
    year_remaining = progress["year_remaining_km"]
    closed = [row for row in months if row["state"] == "past"]
    return {
        **progress,
        "year": year,
        "year_state": year_state,
        "focus_month": focus_month,
        "year_expected_km_to_date": expected,
        "year_pace_delta_km": round_metric(progress["ytd_km"] - expected),
        "year_remaining_days": remaining_days,
        "required_weekly_km": (
            round_metric(year_remaining / remaining_days * 7)
            if year_state == "current" and remaining_days > 0
            else None
        ),
        "months_closed": len(closed),
        "months_met": sum(1 for row in closed if row["met"]),
        "months": months,
    }
