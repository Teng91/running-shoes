"""Transactional mileage updates shared by run and import use cases."""

from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models
from backend.run_metrics import counts_toward_training
from backend.services.identifiers import allocate_id

# (shoe_id, date, km, activity_type) of one run side; a negative km removes it.
RunDelta = tuple[int, str, float, str]


def apply_run_mileage_deltas(
    db: Session,
    user_id: int,
    run_values: Sequence[RunDelta],
    multiplier: int,
) -> float:
    """Apply run deltas to shoe and monthly totals inside the caller's transaction.

    Every activity type wears the shoe; only training types (SPEC-096) add to the
    month, so a hike changes shoe mileage but not monthly volume. Returns the shoe
    (all-activity) delta.
    """
    shoe_deltas: dict[int, float] = {}
    month_deltas: dict[tuple[int, int], float] = {}
    total_delta = 0.0
    for shoe_id, run_date, km, activity_type in run_values:
        delta = round(km * multiplier, 2)
        shoe_deltas[shoe_id] = shoe_deltas.get(shoe_id, 0.0) + delta
        if counts_toward_training(activity_type):
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
                    func.round(func.coalesce(models.Shoe.mileage, 0) + round(delta, 2), 2),
                ),
            },
            synchronize_session=False,
        )

    for (year, month), delta in month_deltas.items():
        if abs(delta) < 0.005:
            continue
        rounded_delta = round(delta, 2)
        # Callers hold the SQLite writer reservation, so update-then-insert is
        # race free and a new identifier is only allocated for a new month.
        changed = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.user_id == user_id,
            models.MonthlyMileage.year == year,
            models.MonthlyMileage.month == month,
        ).update(
            {
                models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
                models.MonthlyMileage.km: func.max(
                    0,
                    func.round(func.coalesce(models.MonthlyMileage.km, 0) + rounded_delta, 2),
                ),
            },
            synchronize_session=False,
        )
        if not changed and rounded_delta > 0:
            db.add(models.MonthlyMileage(
                id=allocate_id(db, "monthly_mileages"), user_id=user_id, year=year, month=month,
                km=rounded_delta, adjustment_km=0, version=0,
            ))
            db.flush()
    return round(total_delta, 2)
