"""User-scoped calendar boundaries and aggregate run distances shared by adapters."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.models import Run
from backend.read_models.rounding import round_metric
from backend.run_metrics import PACE_ACTIVITY_TYPES, TRAINING_ACTIVITY_TYPES

# SPEC-096: shared filters. Volume, goals and streaks read training runs; pace
# and race readiness read pace runs; shoe statistics read every run.
TRAINING_RUN = Run.activity_type.in_(TRAINING_ACTIVITY_TYPES)
PACE_RUN = Run.activity_type.in_(PACE_ACTIVITY_TYPES)


@dataclass(frozen=True)
class RunPeriod:
    month_start: str
    month_end: str
    previous_start: str
    previous_end: str
    ytd_start: str
    ytd_end: str
    comparison_day: int
    comparison_label: str


def month_bounds(year: int, month: int) -> tuple[str, str]:
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"


def run_period(year: int, month: int, as_of: date) -> RunPeriod:
    start, end = month_bounds(year, month)
    previous_date = date(year, month, 1) - timedelta(days=1)
    previous_start, previous_end = month_bounds(previous_date.year, previous_date.month)
    selected, current = (year, month), (as_of.year, as_of.month)
    day, label = monthrange(year, month)[1], "與上月比較"
    ytd_end = end if selected < current else as_of.isoformat()
    if selected == current:
        end = as_of.isoformat()
        day, label = as_of.day, "較上月同期"
        previous_end = previous_date.replace(day=min(day, previous_date.day)).isoformat()
    elif selected > current:
        # An empty range expresses future periods without reading future records.
        end = (date(year, month, 1) - timedelta(days=1)).isoformat()
        previous_end = (previous_date.replace(day=1) - timedelta(days=1)).isoformat()
        day, label = 0, "尚未開始"
    return RunPeriod(
        start, end, previous_start, previous_end, f"{year:04d}-01-01", ytd_end, day, label
    )


def sum_run_distance(db: Session, user_id: int, start: str, end: str) -> float:
    value = (
        db.query(func.sum(Run.km))
        .filter(
            Run.user_id == user_id,
            TRAINING_RUN,
            Run.date >= start,
            Run.date <= end,
        )
        .scalar()
    )
    return round_metric(value)


def period_distances(db: Session, user_id: int, period: RunPeriod) -> dict[str, float]:
    """One bounded conditional aggregate, including YTD irrespective of month number."""
    windows = {
        "month_km": (period.month_start, period.month_end),
        "previous_km": (period.previous_start, period.previous_end),
        "ytd_km": (period.ytd_start, period.ytd_end),
    }
    row = (
        db.query(
            *[
                func.sum(case(((Run.date >= start) & (Run.date <= end), Run.km), else_=0))
                for start, end in windows.values()
            ]
        )
        .filter(
            Run.user_id == user_id,
            TRAINING_RUN,
            Run.date >= min(start for start, _ in windows.values()),
            Run.date <= max(end for _, end in windows.values()),
        )
        .one()
    )
    return {key: round_metric(float(value or 0), 2) for key, value in zip(windows, row, strict=True)}


def monthly_run_distances(db: Session, user_id: int, year: int, through: date) -> list[float]:
    """Twelve logged-run monthly totals for ``year``, ignoring runs dated after ``through``."""
    end = min(date(year, 12, 31), through)
    if end.year < year:
        return [0.0] * 12
    month = func.substr(Run.date, 6, 2)
    rows = (
        db.query(month, func.sum(Run.km))
        .filter(
            Run.user_id == user_id,
            TRAINING_RUN,
            Run.date >= f"{year:04d}-01-01",
            Run.date <= end.isoformat(),
        )
        .group_by(month)
        .all()
    )
    totals = [0.0] * 12
    for number, km in rows:
        totals[int(number) - 1] = round_metric(km)
    return totals
