"""User-scoped monthly application mutations and transaction ownership."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.read_models.run_statistics import month_bounds, sum_run_distance
from backend.services.errors import Conflict, Invalid, NotFound
from backend.services.identifiers import allocate_id
from backend.services.transactions import write_transaction


def _logged_km(db: Session, user_id: int, year: int, month: int):
    return sum_run_distance(db, user_id, *month_bounds(year, month))


def create_monthly_mileage(db: Session, user_id: int, payload: schemas.MonthlyMileageCreate):
    with write_transaction(db, user_id, reason="monthly.create"):
        existing = (
            db.query(models.MonthlyMileage)
            .filter(
                models.MonthlyMileage.user_id == user_id,
                models.MonthlyMileage.year == payload.year,
                models.MonthlyMileage.month == payload.month,
            )
            .first()
        )
        if existing:
            raise Invalid("該月份已有紀錄")
        logged_total = _logged_km(db, user_id, payload.year, payload.month)
        if payload.km + 0.005 < logged_total:
            raise Invalid(f"月跑量不可低於逐筆跑步日誌合計 {logged_total:.2f} km")
        entry = models.MonthlyMileage(
            id=allocate_id(db, "monthly_mileages"), **payload.model_dump(),
            adjustment_km=round(payload.km - logged_total, 2),
            user_id=user_id,
        )
        db.add(entry)
        return entry


def update_monthly_mileage(
    db: Session, user_id: int, entry_id: int, payload: schemas.MonthlyMileageUpdate
):
    with write_transaction(db, user_id, reason="monthly.update"):
        entry = (
            db.query(models.MonthlyMileage)
            .filter(models.MonthlyMileage.id == entry_id, models.MonthlyMileage.user_id == user_id)
            .first()
        )
        if not entry:
            raise NotFound("Monthly mileage not found")
        update_data = payload.model_dump(exclude_unset=True)
        expected_version = update_data.pop("expected_version", getattr(entry, "version", 0))
        new_month = update_data.get("month", entry.month)
        new_year = update_data.get("year", entry.year)
        if ("year" in update_data or "month" in update_data) and (
            new_year != entry.year or new_month != entry.month
        ):
            if _logged_km(db, user_id, entry.year, entry.month) > 0.005:
                raise Invalid("此月份已有逐筆跑步日誌，請先修改跑步日期，不能直接移動月份")
            clash = (
                db.query(models.MonthlyMileage)
                .filter(
                    models.MonthlyMileage.user_id == user_id,
                    models.MonthlyMileage.year == new_year,
                    models.MonthlyMileage.month == new_month,
                    models.MonthlyMileage.id != entry_id,
                )
                .first()
            )
            if clash:
                raise Invalid("該月份已有紀錄")
        desired_total = float(update_data.get("km", entry.km))
        logged_total = _logged_km(db, user_id, new_year, new_month)
        if desired_total + 0.005 < logged_total:
            raise Invalid(f"月跑量不可低於逐筆跑步日誌合計 {logged_total:.2f} km")
        update_data["adjustment_km"] = round(desired_total - logged_total, 2)
        try:
            changed = (
                db.query(models.MonthlyMileage)
                .filter(
                    models.MonthlyMileage.id == entry_id,
                    models.MonthlyMileage.user_id == user_id,
                    models.MonthlyMileage.version == expected_version,
                )
                .update(
                    {
                        **{
                            getattr(models.MonthlyMileage, key): value
                            for key, value in update_data.items()
                        },
                        models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
                    },
                    synchronize_session=False,
                )
            )
            if not changed:
                raise Conflict("月跑量已被更新，請重新載入後再編輯")
        except IntegrityError as exc:
            raise Invalid("該月份已有紀錄") from exc
        return entry


def delete_monthly_mileage(
    db: Session, user_id: int, entry_id: int, expected_version: int | None = None
):
    with write_transaction(db, user_id, reason="monthly.delete"):
        entry = (
            db.query(models.MonthlyMileage)
            .filter(models.MonthlyMileage.id == entry_id, models.MonthlyMileage.user_id == user_id)
            .first()
        )
        if not entry:
            raise NotFound("Monthly mileage not found")
        version = getattr(entry, "version", 0) if expected_version is None else expected_version
        logged_total = _logged_km(db, user_id, entry.year, entry.month)
        query = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.id == entry_id,
            models.MonthlyMileage.user_id == user_id,
            models.MonthlyMileage.version == version,
        )
        if logged_total:
            changed = query.update(
                {
                    models.MonthlyMileage.adjustment_km: 0,
                    models.MonthlyMileage.km: logged_total,
                    models.MonthlyMileage.version: models.MonthlyMileage.version + 1,
                },
                synchronize_session=False,
            )
        else:
            changed = query.delete(synchronize_session=False)
        if not changed:
            raise Conflict("月跑量已被更新，請重新載入後再刪除")
        return {"ok": True}
