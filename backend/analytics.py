"""Deterministic running and shoe analytics shared by the dashboard and API."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import goals, models


def _round(value: float | None, digits: int = 2) -> float:
    return round(float(value or 0), digits)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def _run_metrics(runs: list[models.Run]) -> dict:
    total_km = _round(sum(run.km for run in runs))
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

    as_of = today or datetime.now(timezone(timedelta(hours=8))).date()
    runs = db.query(models.Run).filter(
        models.Run.user_id == user_id,
        models.Run.shoe_id == shoe.id,
    ).order_by(models.Run.date, models.Run.id).all()
    metrics = _run_metrics(runs)
    cutoff_30 = (as_of - timedelta(days=29)).isoformat()
    cutoff_90 = (as_of - timedelta(days=89)).isoformat()
    km_30 = _round(sum(run.km for run in runs if cutoff_30 <= run.date <= as_of.isoformat()))
    km_90 = _round(sum(run.km for run in runs if cutoff_90 <= run.date <= as_of.isoformat()))
    actual_monthly_rate = _round(km_90 / 90 * 30.4375) if km_90 > 0 else 0.0
    remaining = _round(max(0, shoe.expected_mileage - shoe.mileage))
    forecast_rate = actual_monthly_rate or _round(shoe.monthly_km)
    forecast_source = "recent_90_days" if actual_monthly_rate > 0 else "planned_monthly_km"
    forecast_date = None
    if remaining > 0 and forecast_rate > 0:
        forecast_days = round(remaining / forecast_rate * 30.4375)
        forecast_date = (as_of + timedelta(days=forecast_days)).isoformat()

    monthly: dict[tuple[int, int], dict[str, float | int]] = defaultdict(
        lambda: {"km": 0.0, "count": 0}
    )
    for run in runs:
        key = (int(run.date[:4]), int(run.date[5:7]))
        monthly[key]["km"] = float(monthly[key]["km"]) + run.km
        monthly[key]["count"] = int(monthly[key]["count"]) + 1
    monthly_history = []
    for offset in range(-11, 1):
        year, month = _shift_month(as_of.year, as_of.month, offset)
        values = monthly[(year, month)]
        monthly_history.append({
            "year": year,
            "month": month,
            "km": _round(float(values["km"])),
            "count": int(values["count"]),
        })

    reconciled_total = _round(shoe.baseline_mileage + metrics["km"])
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
            "total_mileage_km": _round(shoe.mileage),
            "logged_mileage_km": metrics["km"],
            "historical_adjustment_km": _round(shoe.baseline_mileage),
            "reconciled_total_km": reconciled_total,
            "reconciliation_difference_km": _round(shoe.mileage - reconciled_total),
            "expected_mileage_km": _round(shoe.expected_mileage),
            "remaining_mileage_km": remaining,
            "usage_percent": (
                _round(shoe.mileage / shoe.expected_mileage * 100, 1)
                if shoe.expected_mileage > 0 else None
            ),
            "forecast_retirement_date": forecast_date,
            "forecast_monthly_km": forecast_rate,
            "forecast_source": forecast_source,
        },
        "usage": {
            **metrics,
            "first_run_date": runs[0].date if runs else None,
            "last_run_date": runs[-1].date if runs else None,
            "km_30_days": km_30,
            "km_90_days": km_90,
            "actual_monthly_km_90_days": actual_monthly_rate,
            "cost_per_km": _round(shoe.price / shoe.mileage) if shoe.mileage > 0 else None,
            "cost_per_wear": _round(shoe.price / len(runs)) if runs else None,
        },
        "monthly_history": monthly_history,
        "recent_runs": [
            {
                "id": run.id,
                "date": run.date,
                "km": _round(run.km),
            }
            for run in reversed(runs[-12:])
        ],
    }


def dashboard_analytics(
    db: Session,
    user_id: int,
    year: int,
    month: int,
    *,
    today: date | None = None,
) -> dict:
    as_of = today or datetime.now(timezone(timedelta(hours=8))).date()
    prefix = f"{year:04d}-{month:02d}-"
    prev_year, prev_month = _shift_month(year, month, -1)
    prev_prefix = f"{prev_year:04d}-{prev_month:02d}-"
    month_runs = db.query(models.Run).filter(
        models.Run.user_id == user_id,
        models.Run.date.like(prefix + "%"),
    ).all()
    prev_runs = db.query(models.Run).filter(
        models.Run.user_id == user_id,
        models.Run.date.like(prev_prefix + "%"),
    ).all()
    month_metrics = _run_metrics(month_runs)
    prev_metrics = _run_metrics(prev_runs)

    shoe_ids = {run.shoe_id for run in month_runs}
    shoe_rows: list[models.Shoe] = []
    if shoe_ids:
        shoe_rows = db.query(models.Shoe).filter(
            models.Shoe.user_id == user_id,
            models.Shoe.id.in_(shoe_ids),
        ).all()
    shoe_map = {shoe.id: shoe for shoe in shoe_rows}
    per_shoe: dict[int, dict[str, float | int]] = defaultdict(
        lambda: {"km": 0.0, "count": 0}
    )
    for run in month_runs:
        per_shoe[run.shoe_id]["km"] = float(per_shoe[run.shoe_id]["km"]) + run.km
        per_shoe[run.shoe_id]["count"] = int(per_shoe[run.shoe_id]["count"]) + 1
    shoe_usage: list[dict[str, float | int | str]] = []
    for shoe_id, values in sorted(per_shoe.items(), key=lambda item: float(item[1]["km"]), reverse=True):
        shoe = shoe_map.get(shoe_id)
        km = _round(float(values["km"]))
        shoe_usage.append({
            "shoe_id": shoe_id,
            "name": f"{shoe.brand} {shoe.model}" if shoe else "鞋款已刪除",
            "km": km,
            "count": int(values["count"]),
            "share_percent": _round(km / month_metrics["km"] * 100, 1)
            if month_metrics["km"] > 0 else 0.0,
        })

    selected = (year, month)
    current = (as_of.year, as_of.month)
    if selected < current:
        end_7 = date(year, month, monthrange(year, month)[1])
    elif selected == current:
        end_7 = as_of
    else:
        end_7 = date(year, month, 1)
    start_7 = end_7 - timedelta(days=6)
    start_prev_7 = start_7 - timedelta(days=7)
    all_recent = db.query(models.Run).filter(
        models.Run.user_id == user_id,
        models.Run.date >= start_prev_7.isoformat(),
        models.Run.date <= end_7.isoformat(),
    ).all()
    latest_7_km = _round(sum(run.km for run in all_recent if run.date >= start_7.isoformat()))
    previous_7_km = _round(sum(run.km for run in all_recent if run.date < start_7.isoformat()))

    active_shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
        models.Shoe.is_retired.is_(False),
    ).all()
    alerts = []
    for shoe in active_shoes:
        if shoe.expected_mileage <= 0:
            continue
        pct = shoe.mileage / shoe.expected_mileage * 100
        if pct >= 80:
            alerts.append({
                "type": "lifecycle",
                "severity": "urgent" if pct >= 100 else "warning",
                "shoe_id": shoe.id,
                "message": f"{shoe.brand} {shoe.model} 已使用 {pct:.1f}% 預期壽命",
            })
    if len(active_shoes) > 1 and shoe_usage and month_metrics["count"] >= 3:
        leader = shoe_usage[0]
        leader_share = float(leader["share_percent"])
        if leader_share >= 70:
            alerts.append({
                "type": "rotation",
                "severity": "info",
                "shoe_id": int(leader["shoe_id"]),
                "message": f"{leader['name']} 承擔本月 {leader_share:.1f}% 里程，可考慮增加輪替",
            })

    return {
        "period": {"year": year, "month": month},
        "month": month_metrics,
        "previous_month": {"year": prev_year, "month": prev_month, **prev_metrics},
        "month_delta_km": _round(month_metrics["km"] - prev_metrics["km"]),
        "recent_7_days": {
            "start": start_7.isoformat(),
            "end": end_7.isoformat(),
            "km": latest_7_km,
            "previous_km": previous_7_km,
            "delta_km": _round(latest_7_km - previous_7_km),
        },
        "goal": goals.goal_progress(db, user_id, year, month, as_of=as_of),
        "shoe_usage": shoe_usage,
        "alerts": alerts,
    }


def mileage_reconciliation(db: Session, user_id: int) -> dict:
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
    ).all()
    shoe_rows = []
    consistent = True
    for shoe in shoes:
        logged = db.query(func.sum(models.Run.km)).filter(
            models.Run.user_id == user_id,
            models.Run.shoe_id == shoe.id,
        ).scalar()
        expected = _round(shoe.baseline_mileage + float(logged or 0))
        difference = _round(shoe.mileage - expected)
        consistent = consistent and abs(difference) < 0.01
        shoe_rows.append({
            "shoe_id": shoe.id,
            "name": f"{shoe.brand} {shoe.model}",
            "total_km": _round(shoe.mileage),
            "logged_km": _round(logged),
            "historical_adjustment_km": _round(shoe.baseline_mileage),
            "difference_km": difference,
        })

    months = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == user_id,
    ).order_by(models.MonthlyMileage.year, models.MonthlyMileage.month).all()
    month_rows = []
    for row in months:
        logged = db.query(func.sum(models.Run.km)).filter(
            models.Run.user_id == user_id,
            models.Run.date.like(f"{row.year:04d}-{row.month:02d}-%"),
        ).scalar()
        expected = _round(row.adjustment_km + float(logged or 0))
        difference = _round(row.km - expected)
        consistent = consistent and abs(difference) < 0.01
        month_rows.append({
            "year": row.year,
            "month": row.month,
            "total_km": _round(row.km),
            "logged_km": _round(logged),
            "historical_adjustment_km": _round(row.adjustment_km),
            "difference_km": difference,
        })
    return {
        "ok": consistent,
        "shoes": shoe_rows,
        "months": month_rows,
    }
