"""Transactional mileage updates shared by run and import use cases."""

from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend import models
from backend.services.identifiers import allocate_id


def apply_run_mileage_deltas(
    db: Session,
    user_id: int,
    run_values: Sequence[tuple[int, str, float]],
    multiplier: int,
) -> float:
    """Apply run deltas to shoe and monthly totals inside the caller's transaction."""
    shoe_deltas: dict[int, float] = {}
    month_deltas: dict[tuple[int, int], float] = {}
    total_delta = 0.0
    for shoe_id, run_date, km in run_values:
        delta = round(km * multiplier, 2)
        shoe_deltas[shoe_id] = shoe_deltas.get(shoe_id, 0.0) + delta
        year, month = int(run_date[:4]), int(run_date[5:7])
        month_deltas[(year, month)] = month_deltas.get((year, month), 0.0) + delta
        total_delta += delta

    for shoe_id, delta in shoe_deltas.items():
        if abs(delta) < 0.005:
            continue
        db.query(models.Shoe).filter(
            models.Shoe.id == shoe_id,
            models.Shoe.user_id == user_id,
        ).update(
            {
                models.Shoe.version: models.Shoe.version + 1,
                models.Shoe.mileage: func.max(
                    0,
                    func.coalesce(models.Shoe.mileage, 0) + round(delta, 2),
                ),
            },
            synchronize_session=False,
        )

    for (year, month), delta in month_deltas.items():
        if abs(delta) < 0.005:
            continue
        rounded_delta = round(delta, 2)
        if rounded_delta > 0:
            statement = sqlite_insert(models.MonthlyMileage).values(
                id=allocate_id(db, "monthly_mileages"), user_id=user_id,
                year=year,
                month=month,
                km=rounded_delta,
                adjustment_km=0,
                version=0,
            )
            statement = statement.on_conflict_do_update(
                index_elements=["user_id", "year", "month"],
                set_={
                    "km": func.max(
                        0,
                        func.coalesce(models.MonthlyMileage.km, 0) + rounded_delta,
                    ),
                    "version": models.MonthlyMileage.version + 1,
                },
            )
            db.execute(statement)
        else:
            db.query(models.MonthlyMileage).filter(
                models.MonthlyMileage.user_id == user_id,
                models.MonthlyMileage.year == year,
                models.MonthlyMileage.month == month,
            ).update(
                {
                    models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
                    models.MonthlyMileage.km: func.max(
                        0,
                        func.coalesce(models.MonthlyMileage.km, 0) + rounded_delta,
                    ),
                },
                synchronize_session=False,
            )
    return round(total_delta, 2)


def reconcile_account_mileage(db: Session, uid: int) -> None:
    """Keep local-only runs while replacing source baseline/adjustment values."""
    by_shoe = {shoe_id: float(km) for shoe_id, km in db.query(models.Run.shoe_id, func.sum(models.Run.km)).filter_by(user_id=uid).group_by(models.Run.shoe_id).all()}
    for shoe in db.query(models.Shoe).filter_by(user_id=uid).all():
        total = round(shoe.baseline_mileage + float(by_shoe.get(shoe.id, 0)), 2)
        if shoe.mileage != total:
            shoe.mileage = total
            shoe.version += 1
    periods = {(row.year, row.month): row for row in db.query(models.MonthlyMileage).filter_by(user_id=uid).all()}
    totals = {(int(year), int(month)): float(km) for year, month, km in db.query(
        func.substr(models.Run.date, 1, 4), func.substr(models.Run.date, 6, 2), func.sum(models.Run.km),
    ).filter_by(user_id=uid).group_by(func.substr(models.Run.date, 1, 7)).all()}
    for period in periods.keys() | totals.keys():
        row = periods.get(period)
        if row is None:
            row = models.MonthlyMileage(id=allocate_id(db, "monthly_mileages"), user_id=uid, year=period[0], month=period[1], adjustment_km=0)
            db.add(row)
        total = round(float(row.adjustment_km or 0) + totals.get(period, 0), 2)
        if row.km != total:
            row.km = total
            row.version = (row.version or 0) + 1
    db.flush()
