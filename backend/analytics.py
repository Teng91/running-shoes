"""Deterministic running and shoe analytics shared by the dashboard and API."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

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
    selected = (year, month)
    current = (as_of.year, as_of.month)
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

    # An in-progress month must be compared with the same number of calendar
    # days in the previous month.  Finished months retain full-month semantics.
    if selected == current:
        comparison_day = min(as_of.day, monthrange(prev_year, prev_month)[1])
        comparison_month_runs = [run for run in month_runs if int(run.date[8:10]) <= as_of.day]
        comparison_prev_runs = [run for run in prev_runs if int(run.date[8:10]) <= comparison_day]
        comparison_label = "較上月同期"
    elif selected < current:
        comparison_day = monthrange(year, month)[1]
        comparison_month_runs = month_runs
        comparison_prev_runs = prev_runs
        comparison_label = "與上月比較"
    else:
        comparison_day = 0
        comparison_month_runs = []
        comparison_prev_runs = []
        comparison_label = "尚未開始"
    comparison_current = _run_metrics(comparison_month_runs)
    comparison_previous = _run_metrics(comparison_prev_runs)

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

    if selected < current:
        end_7 = date(year, month, monthrange(year, month)[1])
    elif selected == current:
        end_7 = as_of
    else:
        end_7 = None
    if end_7 is None:
        start_7 = None
        all_recent: list[models.Run] = []
        latest_7_km = 0.0
        previous_7_km = 0.0
    else:
        start_7 = end_7 - timedelta(days=6)
        start_prev_7 = start_7 - timedelta(days=7)
        all_recent = db.query(models.Run).filter(
            models.Run.user_id == user_id,
            models.Run.date >= start_prev_7.isoformat(),
            models.Run.date <= end_7.isoformat(),
        ).all()
        latest_7_km = _round(
            sum(run.km for run in all_recent if run.date >= start_7.isoformat())
        )
        previous_7_km = _round(
            sum(run.km for run in all_recent if run.date < start_7.isoformat())
        )

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
        if pct >= 80:
            alerts.append({
                "type": "lifecycle",
                "severity": "urgent" if pct >= 100 else "warning",
                "shoe_id": shoe.id,
                "message": f"{shoe.brand} {shoe.model} 已使用 {pct:.1f}% 預期壽命",
            })
    # 30/90-day shoe rotation uses the selected period's effective end date.
    analysis_end = (
        date(year, month, monthrange(year, month)[1])
        if selected < current
        else as_of if selected == current else None
    )
    recent_90: list[models.Run] = []
    if analysis_end is not None:
        recent_90 = db.query(models.Run).filter(
            models.Run.user_id == user_id,
            models.Run.date >= (analysis_end - timedelta(days=89)).isoformat(),
            models.Run.date <= analysis_end.isoformat(),
        ).all()
    rotation_totals: dict[int, dict[str, float | int]] = defaultdict(
        lambda: {"km_30": 0.0, "count_30": 0, "km_90": 0.0, "count_90": 0}
    )
    cutoff_30 = analysis_end - timedelta(days=29) if analysis_end else None
    for run in recent_90:
        values = rotation_totals[run.shoe_id]
        values["km_90"] = float(values["km_90"]) + run.km
        values["count_90"] = int(values["count_90"]) + 1
        if cutoff_30 and run.date >= cutoff_30.isoformat():
            values["km_30"] = float(values["km_30"]) + run.km
            values["count_30"] = int(values["count_30"]) + 1
    total_30 = sum(float(item["km_30"]) for item in rotation_totals.values())
    total_90 = sum(float(item["km_90"]) for item in rotation_totals.values())
    rotation_shoes: list[dict[str, Any]] = []
    for shoe in active_shoes:
        values = rotation_totals[shoe.id]
        km_30 = _round(float(values["km_30"]))
        km_90 = _round(float(values["km_90"]))
        usage_percent = (
            _round(shoe.mileage / shoe.expected_mileage * 100, 1)
            if shoe.expected_mileage > 0 else None
        )
        rotation_shoes.append({
            "shoe_id": shoe.id,
            "name": f"{shoe.brand} {shoe.model}",
            "categories": shoe.categories or [],
            "km_30": km_30,
            "count_30": int(values["count_30"]),
            "share_30_percent": _round(km_30 / total_30 * 100, 1) if total_30 else 0.0,
            "km_90": km_90,
            "count_90": int(values["count_90"]),
            "share_90_percent": _round(km_90 / total_90 * 100, 1) if total_90 else 0.0,
            "usage_percent": usage_percent,
        })
    rotation_shoes.sort(key=lambda item: float(item["km_90"]), reverse=True)
    concentrated = bool(
        rotation_shoes
        and total_90 > 0
        and float(rotation_shoes[0]["share_90_percent"]) >= 70
        and int(rotation_shoes[0]["count_90"]) >= 3
    )
    if concentrated:
        leader = rotation_shoes[0]
        alerts.append({
            "type": "rotation",
            "severity": "info",
            "shoe_id": int(leader["shoe_id"]),
            "message": f"{leader['name']} 承擔近 90 天 {leader['share_90_percent']:.1f}% 里程，可考慮增加輪替",
        })
    categories = ("Daily", "Speed", "Tempo", "Race")
    coverage: list[dict[str, Any]] = []
    for category in categories:
        matches = [shoe for shoe in rotation_shoes if category in shoe["categories"]]
        coverage.append({
            "category": category,
            "active_count": len(matches),
            "nearing_retirement_count": sum(
                1 for shoe in matches
                if shoe["usage_percent"] is not None and float(shoe["usage_percent"]) >= 80
            ),
        })
    uncovered = [entry["category"] for entry in coverage if entry["active_count"] == 0]
    fragile = [
        entry["category"] for entry in coverage
        if entry["active_count"] > 0
        and entry["active_count"] == entry["nearing_retirement_count"]
    ]
    next_category = (uncovered or fragile or [None])[0]
    simultaneous_retirement = [
        str(shoe["name"]) for shoe in rotation_shoes
        if shoe["usage_percent"] is not None and float(shoe["usage_percent"]) >= 80
    ]

    goal = goals.goal_progress(db, user_id, year, month, as_of=as_of)
    days_in_month = monthrange(year, month)[1]
    if selected == current:
        projected = _round(goal["month_km"] / max(1, as_of.day) * days_in_month)
        forecast_state = "current"
    elif selected < current:
        projected = _round(goal["month_km"])
        forecast_state = "past"
    else:
        projected = 0.0
        forecast_state = "future"
    forecast = {
        "state": forecast_state,
        "projected_month_km": projected,
        "daily_average_km": (
            _round(goal["month_km"] / max(1, goal["elapsed_days"]))
            if goal["elapsed_days"] else 0.0
        ),
        "required_daily_km": goal["required_daily_km"],
        "required_weekly_km": (
            _round(float(goal["required_daily_km"]) * 7)
            if goal["required_daily_km"] is not None else None
        ),
        "projected_goal_delta_km": _round(projected - goal["monthly_km"]),
    }

    weekly: list[dict[str, Any]] = []
    rest_streak: int | None
    if analysis_end is not None:
        last_28_start = analysis_end - timedelta(days=27)
        runs_28 = [run for run in recent_90 if run.date >= last_28_start.isoformat()]
        for offset in range(3, -1, -1):
            week_end = analysis_end - timedelta(days=offset * 7)
            week_start = week_end - timedelta(days=6)
            week_runs = [
                run for run in runs_28
                if week_start.isoformat() <= run.date <= week_end.isoformat()
            ]
            weekly.append({
                "start": week_start.isoformat(),
                "end": week_end.isoformat(),
                **_run_metrics(week_runs),
            })
        all_past_runs = db.query(models.Run.date).filter(
            models.Run.user_id == user_id,
            models.Run.date <= analysis_end.isoformat(),
        ).all()
        run_dates = {row[0] for row in all_past_runs}
        if analysis_end.isoformat() in run_dates:
            run_streak = 0
            cursor = analysis_end
            while cursor.isoformat() in run_dates:
                run_streak += 1
                cursor -= timedelta(days=1)
            rest_streak = 0
        else:
            run_streak = 0
            latest = max(run_dates) if run_dates else None
            rest_streak = (
                (analysis_end - date.fromisoformat(latest)).days if latest else None
            )
    else:
        weekly = []
        run_streak = 0
        rest_streak = None
    rolling_4_week_km = _round(sum(float(week["km"]) for week in weekly))
    if previous_7_km >= 5:
        change_percent = _round((latest_7_km - previous_7_km) / previous_7_km * 100, 1)
        load_status = "increase" if change_percent >= 50 else "decrease" if change_percent <= -50 else "steady"
    elif latest_7_km >= 10:
        change_percent = None
        load_status = "increase"
    else:
        change_percent = None
        load_status = "steady"

    year_runs = db.query(models.Run).filter(
        models.Run.user_id == user_id,
        models.Run.date.like(f"{year:04d}-%"),
    ).all()
    activity: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"km": 0.0, "count": 0}
    )
    for run in year_runs:
        activity[run.date]["km"] = float(activity[run.date]["km"]) + run.km
        activity[run.date]["count"] = int(activity[run.date]["count"]) + 1

    return {
        "period": {"year": year, "month": month},
        "month": month_metrics,
        "previous_month": {"year": prev_year, "month": prev_month, **prev_metrics},
        "month_delta_km": _round(comparison_current["km"] - comparison_previous["km"]),
        "comparison": {
            "label": comparison_label,
            "through_day": comparison_day,
            "current_km": comparison_current["km"],
            "previous_km": comparison_previous["km"],
            "delta_km": _round(comparison_current["km"] - comparison_previous["km"]),
        },
        "recent_7_days": {
            "state": "future" if end_7 is None else "ready",
            "start": start_7.isoformat() if start_7 else None,
            "end": end_7.isoformat() if end_7 else None,
            "km": latest_7_km,
            "previous_km": previous_7_km,
            "delta_km": _round(latest_7_km - previous_7_km),
        },
        "goal": goal,
        "forecast": forecast,
        "consistency": {
            "weeks": weekly,
            "rolling_4_week_km": rolling_4_week_km,
            "average_weekly_km": _round(rolling_4_week_km / 4) if weekly else 0.0,
            "average_running_days": (
                _round(sum(int(week["days"]) for week in weekly) / 4, 1)
                if weekly else 0.0
            ),
            "run_streak_days": run_streak,
            "rest_streak_days": rest_streak,
            "load_status": load_status,
            "week_change_percent": change_percent,
        },
        "year_activity": [
            {"date": day, "km": _round(values["km"]), "count": int(values["count"])}
            for day, values in sorted(activity.items())
        ],
        "shoe_usage": shoe_usage,
        "rotation": {
            "shoes": rotation_shoes,
            "concentrated": concentrated,
            "category_coverage": coverage,
            "simultaneous_retirement": simultaneous_retirement,
            "next_category": next_category,
        },
        "alerts": alerts,
    }


def mileage_reconciliation(db: Session, user_id: int) -> dict:
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id,
    ).all()
    shoe_rows = []
    consistent = True
    for shoe in shoes:
        logged = db.query(func.sum(models.Run.km)).filter(
            models.Run.user_id == user_id,
            models.Run.shoe_id == shoe.id,
        ).scalar()
        expected = _round(max(0, shoe.baseline_mileage) + float(logged or 0))
        difference = _round(shoe.mileage - expected)
        consistent = consistent and shoe.baseline_mileage >= 0 and abs(difference) < 0.01
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
    run_month_totals: dict[tuple[int, int], float] = defaultdict(float)
    for run in db.query(models.Run).filter(models.Run.user_id == user_id).all():
        run_month_totals[(int(run.date[:4]), int(run.date[5:7]))] += run.km
    month_map = {(row.year, row.month): row for row in months}
    month_rows = []
    for year, month in sorted(set(month_map) | set(run_month_totals)):
        row = month_map.get((year, month))
        logged = _round(run_month_totals[(year, month)])
        adjustment = float(row.adjustment_km) if row else 0.0
        total = float(row.km) if row else 0.0
        expected = _round(max(0, adjustment) + logged)
        difference = _round(total - expected)
        consistent = consistent and row is not None and adjustment >= 0 and abs(difference) < 0.01
        month_rows.append({
            "year": year,
            "month": month,
            "total_km": _round(total),
            "logged_km": _round(logged),
            "historical_adjustment_km": _round(adjustment),
            "difference_km": difference,
            "missing_aggregate": row is None,
        })
    return {
        "ok": consistent,
        "shoes": shoe_rows,
        "months": month_rows,
    }


def repair_mileage_reconciliation(db: Session, user_id: int) -> dict:
    """Repair only derived totals and clamp invalid historical adjustments to zero."""
    repaired_shoes = 0
    repaired_months = 0
    created_months = 0
    shoes = db.query(models.Shoe).filter(models.Shoe.user_id == user_id).all()
    run_rows = db.query(models.Run).filter(models.Run.user_id == user_id).all()
    shoe_totals: dict[int, float] = defaultdict(float)
    month_totals: dict[tuple[int, int], float] = defaultdict(float)
    for run in run_rows:
        shoe_totals[run.shoe_id] += run.km
        month_totals[(int(run.date[:4]), int(run.date[5:7]))] += run.km
    for shoe in shoes:
        baseline = _round(max(0, shoe.baseline_mileage))
        total = _round(baseline + shoe_totals[shoe.id])
        if abs(shoe.mileage - total) >= 0.005 or abs(shoe.baseline_mileage - baseline) >= 0.005:
            shoe.baseline_mileage = baseline
            shoe.mileage = total
            shoe.version += 1
            repaired_shoes += 1
    month_rows = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == user_id
    ).all()
    month_map = {(row.year, row.month): row for row in month_rows}
    for key in sorted(set(month_map) | set(month_totals)):
        row = month_map.get(key)
        logged = _round(month_totals[key])
        if row is None:
            db.add(models.MonthlyMileage(
                user_id=user_id,
                year=key[0],
                month=key[1],
                km=logged,
                adjustment_km=0,
            ))
            created_months += 1
            continue
        adjustment = _round(max(0, row.adjustment_km))
        total = _round(adjustment + logged)
        if abs(row.km - total) >= 0.005 or abs(row.adjustment_km - adjustment) >= 0.005:
            row.adjustment_km = adjustment
            row.km = total
            row.version += 1
            repaired_months += 1
    db.flush()
    return {
        "repaired_shoes": repaired_shoes,
        "repaired_months": repaired_months,
        "created_months": created_months,
    }
