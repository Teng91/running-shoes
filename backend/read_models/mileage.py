"""Historical monthly mileage read model shared by reports and tools."""

from sqlalchemy.orm import Session

from backend import models


def _round(value: float | None, digits: int = 2) -> float:
    return round(float(value or 0), digits)


def monthly_mileage_stats(db: Session, user_id: int) -> dict:
    rows = (
        db.query(models.MonthlyMileage)
        .filter(models.MonthlyMileage.user_id == user_id)
        .order_by(models.MonthlyMileage.year, models.MonthlyMileage.month)
        .all()
    )
    recorded_rows = rows
    rows = [r for r in rows if r.km > 0]
    if not rows:
        return dict(
            ok=True,
            status="no_records" if not recorded_rows else "all_months_zero",
            recorded_month_count=len(recorded_rows),
            nonzero_month_count=0,
            total_mileage_km=0.0,
            recent_nonzero_months=[],
        )

    total = sum(r.km for r in rows)
    avg = total / len(rows)
    recent = rows[-6:]
    recent_total = sum(r.km for r in recent)
    recent_avg = recent_total / len(recent)
    trend = "up" if (recent_avg > avg) else ("down" if recent_avg < avg else "flat")

    last = rows[-1]
    return dict(
        ok=True,
        status="available",
        recorded_month_count=len(recorded_rows),
        nonzero_month_count=len(rows),
        total_mileage_km=_round(total),
        overall_nonzero_month_average_km=_round(avg),
        recent_period_definition="latest_6_months_with_positive_mileage",
        recent_period_month_count=len(recent),
        recent_period_total_km=_round(recent_total),
        recent_period_average_km=_round(recent_avg),
        recent_vs_overall_trend=trend,
        latest_record={"year": last.year, "month": last.month, "mileage_km": _round(last.km)},
        recent_nonzero_months=[
            {"year": row.year, "month": row.month, "mileage_km": _round(row.km)} for row in recent
        ],
    )
