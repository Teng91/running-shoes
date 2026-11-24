"""Deterministic running and shoe analytics shared by the dashboard and API."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.clock import local_today
from backend.forecasting import retirement_forecast
from backend.read_models import goal_progress
from backend.read_models.rounding import round_metric
from backend.read_models.run_statistics import TRAINING_RUN, month_bounds, run_period
from backend.read_models.shoe_statistics import shoe_run_statistics
from backend.shoe_metrics import MONITOR_USAGE_PERCENT, REPLACE_SOON_USAGE_PERCENT, shoe_metrics


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def _run_metrics(runs: list[models.Run]) -> dict:
    total_km = round_metric(sum(run.km for run in runs))
    return {
        "km": total_km,
        "count": len(runs),
        "days": len({run.date for run in runs}),
    }

def shoe_analytics(db: Session, user_id: int, shoe_id: int, *, today: date | None = None) -> dict | None:
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
    ).first()
    if shoe is None:
        return None

    as_of = today or local_today()
    return _shoe_analytics(shoe, shoe_run_statistics(db, user_id, [shoe.id], as_of)[shoe.id], as_of)


def batch_shoe_analytics(
    db: Session, user_id: int, shoes: list[models.Shoe], *, today: date | None = None,
    include_details: bool = True
) -> list[dict]:
    """Three aggregate/window queries for any number of owned shoes."""
    scoped = [shoe for shoe in shoes if shoe.user_id == user_id and not shoe.is_deleted]
    if not scoped:
        return []
    as_of = today or local_today()
    statistics = shoe_run_statistics(
        db, user_id, [shoe.id for shoe in scoped], as_of, include_details=include_details
    )
    return [_shoe_analytics(shoe, statistics[shoe.id], as_of) for shoe in scoped]


def _shoe_analytics(shoe: models.Shoe, statistics: dict, as_of: date) -> dict:
    """One presentation policy for single-shoe API and batched tool read models."""
    metrics = {
        "km": round_metric(statistics["km"]), "count": statistics["count"], "days": statistics["days"],
    }
    km_30, km_90 = round_metric(statistics["km_30"]), round_metric(statistics["km_90"])
    forecast = retirement_forecast(shoe, km_90, as_of, has_runs=statistics["count"] > 0)
    costs = shoe_metrics(shoe)

    monthly_history = []
    for offset in range(-11, 1):
        year, month = _shift_month(as_of.year, as_of.month, offset)
        values = statistics["monthly"].get(f"{year:04d}-{month:02d}", {"km": 0, "count": 0})
        monthly_history.append({
            "year": year,
            "month": month,
            "km": round_metric(float(values["km"])),
            "count": int(values["count"]),
        })

    return {
        "shoe": {
            "id": shoe.id,
            "brand": shoe.brand,
            "model": shoe.model,
            "categories": shoe.categories or [],
            "is_retired": shoe.is_retired,
            "purchase_date": shoe.date,
        },
        "lifecycle": {
            "total_mileage_km": round_metric(shoe.mileage),
            "logged_mileage_km": metrics["km"],
            "historical_adjustment_km": round_metric(shoe.baseline_mileage),
            "expected_mileage_km": round_metric(shoe.expected_mileage),
            "remaining_mileage_km": forecast["remaining_mileage_km"],
            "usage_percent": (
                round_metric(costs["usage_percent"], 1)
                if shoe.expected_mileage > 0 else None
            ),
            "forecast_retirement_date": forecast["forecast_retirement_date"],
            "forecast_monthly_km": forecast["forecast_monthly_km"],
            "forecast_source": forecast["forecast_source"],
        },
        "usage": {
            **metrics,
            "first_run_date": statistics["first"],
            "last_run_date": statistics["last"],
            "km_30_days": km_30,
            "km_90_days": km_90,
            "actual_monthly_km_90_days": forecast["actual_monthly_km_90_days"],
            "cost_per_km": costs["cost_per_km"],
            "cost_per_wear": round_metric(shoe.price / metrics["count"]) if metrics["count"] else None,
            "average_pace_seconds_per_km": statistics["average_pace"],
        },
        "monthly_history": monthly_history,
        "recent_runs": statistics["recent"],
    }


def dashboard_analytics(
    db: Session,
    user_id: int,
    year: int,
    month: int,
    *,
    today: date | None = None,
) -> dict:
    as_of = today or local_today()
    selected = (year, month)
    current = (as_of.year, as_of.month)
    period = run_period(year, month, as_of)
    prev_year, prev_month = _shift_month(year, month, -1)
    prev_start, prev_end = month_bounds(prev_year, prev_month)
    # Monthly summaries count training runs only; hikes stay on the shoe (SPEC-096).
    month_runs = db.query(models.Run).filter(
        models.Run.user_id == user_id, TRAINING_RUN,
        models.Run.date >= period.month_start, models.Run.date <= period.month_end,
    ).all()
    if selected == current:
        month_runs = [run for run in month_runs if run.date <= as_of.isoformat()]
    elif selected > current:
        month_runs = []
    prev_runs = db.query(models.Run).filter(
        models.Run.user_id == user_id, TRAINING_RUN,
        models.Run.date >= prev_start, models.Run.date <= prev_end,
    ).all()
    month_metrics = _run_metrics(month_runs)
    prev_metrics = _run_metrics(prev_runs)
    comparison_current = _run_metrics(month_runs)
    comparison_previous = _run_metrics([run for run in prev_runs if run.date <= period.previous_end])
    goal = goal_progress.goal_progress(db, user_id, year, month, as_of=as_of)

    return {
        "period": {"year": year, "month": month},
        "month": month_metrics,
        "previous_month": {"year": prev_year, "month": prev_month, **prev_metrics},
        "month_delta_km": round_metric(comparison_current["km"] - comparison_previous["km"]),
        "comparison": {
            "label": period.comparison_label,
            "through_day": period.comparison_day,
            "current_km": comparison_current["km"],
            "previous_km": comparison_previous["km"],
            "delta_km": round_metric(comparison_current["km"] - comparison_previous["km"]),
        },
        "recent_7_days": _recent_seven_days(db, user_id, _seven_day_end(selected, current, as_of)),
        "goal": goal,
        "forecast": _month_forecast(goal, selected, current, as_of),
        "shoe_usage": _month_shoe_usage(db, user_id, month_runs, month_metrics["km"]),
        "alerts": _lifecycle_alerts(db, user_id),
    }


def _month_shoe_usage(db: Session, user_id: int, month_runs: list[models.Run], month_km: float) -> list[dict]:
    """Each shoe's share of the month, largest first; a deleted shoe keeps its kilometres."""
    shoe_ids = {run.shoe_id for run in month_runs}
    shoe_rows: list[models.Shoe] = []
    if shoe_ids:
        shoe_rows = db.query(models.Shoe).filter(
            models.Shoe.user_id == user_id,
            models.Shoe.is_deleted.is_(False),
            models.Shoe.id.in_(shoe_ids),
        ).all()
    shoe_map = {shoe.id: shoe for shoe in shoe_rows}
    per_shoe: dict[int, dict[str, float | int]] = defaultdict(
        lambda: {"km": 0.0, "count": 0}
    )
    for run in month_runs:
        per_shoe[run.shoe_id]["km"] = float(per_shoe[run.shoe_id]["km"]) + run.km
        per_shoe[run.shoe_id]["count"] = int(per_shoe[run.shoe_id]["count"]) + 1
    shoe_usage: list[dict] = []
    for shoe_id, values in sorted(per_shoe.items(), key=lambda item: float(item[1]["km"]), reverse=True):
        shoe = shoe_map.get(shoe_id)
        km = round_metric(float(values["km"]))
        shoe_usage.append({
            "shoe_id": shoe_id,
            "name": f"{shoe.brand} {shoe.model}" if shoe else "鞋款已刪除",
            "km": km,
            "count": int(values["count"]),
            "share_percent": round_metric(km / month_km * 100, 1) if month_km > 0 else 0.0,
        })
    return shoe_usage


def _seven_day_end(selected: tuple[int, int], current: tuple[int, int], as_of: date) -> date | None:
    """A past month's last day, today for the current month, nothing for a future month."""
    if selected < current:
        year, month = selected
        return date(year, month, monthrange(year, month)[1])
    return as_of if selected == current else None


def _recent_seven_days(db: Session, user_id: int, end_7: date | None) -> dict:
    """Training kilometres in the seven days ending at end_7 and the seven days before."""
    if end_7 is None:
        return {"state": "future", "start": None, "end": None, "km": 0.0, "previous_km": 0.0,
                "delta_km": round_metric(0.0)}
    start_7 = end_7 - timedelta(days=6)
    start_prev_7 = start_7 - timedelta(days=7)
    all_recent = db.query(models.Run).filter(
        models.Run.user_id == user_id, TRAINING_RUN,
        models.Run.date >= start_prev_7.isoformat(),
        models.Run.date <= end_7.isoformat(),
    ).all()
    latest_7_km = round_metric(sum(run.km for run in all_recent if run.date >= start_7.isoformat()))
    previous_7_km = round_metric(sum(run.km for run in all_recent if run.date < start_7.isoformat()))
    return {
        "state": "ready",
        "start": start_7.isoformat(),
        "end": end_7.isoformat(),
        "km": latest_7_km,
        "previous_km": previous_7_km,
        "delta_km": round_metric(latest_7_km - previous_7_km),
    }


def _lifecycle_alerts(db: Session, user_id: int) -> list[dict]:
    active_shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
        models.Shoe.is_retired.is_(False),
    ).all()
    alerts: list[dict] = []
    for shoe in active_shoes:
        if shoe.expected_mileage <= 0:
            continue
        pct = shoe.mileage / shoe.expected_mileage * 100
        if pct >= MONITOR_USAGE_PERCENT:
            alerts.append({
                "type": "lifecycle",
                "severity": "urgent" if pct >= REPLACE_SOON_USAGE_PERCENT else "warning",
                "shoe_id": shoe.id,
                "message": f"{shoe.brand} {shoe.model} 已使用 {pct:.1f}% 預期壽命",
            })
    return alerts


def _month_forecast(goal: dict, selected: tuple[int, int], current: tuple[int, int], as_of: date) -> dict:
    """The current month projects today's pace; a past month is final; a future one is zero."""
    days_in_month = monthrange(*selected)[1]
    if selected == current:
        projected = round_metric(goal["month_km"] / max(1, as_of.day) * days_in_month)
        forecast_state = "current"
    elif selected < current:
        projected = round_metric(goal["month_km"])
        forecast_state = "past"
    else:
        projected = 0.0
        forecast_state = "future"
    return {
        "state": forecast_state,
        "projected_month_km": projected,
        "daily_average_km": (
            round_metric(goal["month_km"] / max(1, goal["elapsed_days"]))
            if goal["elapsed_days"] else 0.0
        ),
        "required_daily_km": goal["required_daily_km"],
        "required_weekly_km": (
            round_metric(float(goal["required_daily_km"]) * 7)
            if goal["required_daily_km"] is not None else None
        ),
        "projected_goal_delta_km": round_metric(projected - goal["monthly_km"]),
    }
