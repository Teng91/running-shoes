"""User-scoped shoes application mutations and transaction ownership."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.services.errors import Conflict, Invalid, NotFound
from backend.services.transactions import write_transaction


def create_shoe(db: Session, user_id: int, payload: schemas.ShoeCreate, *, max_shoes: int):
    with write_transaction(db, user_id, reason="shoe.create"):
        shoe_count = (
            db.query(models.Shoe)
            .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False))
            .count()
        )
        if isinstance(shoe_count, int) and shoe_count >= max_shoes:
            raise Conflict("跑鞋資料已達上限")
        shoe = models.Shoe(
            **payload.model_dump(), baseline_mileage=payload.mileage, user_id=user_id
        )
        db.add(shoe)
        return shoe


def update_shoe(db: Session, user_id: int, shoe_id: int, payload: schemas.ShoeUpdate):
    with write_transaction(db, user_id, reason="shoe.update"):
        shoe = (
            db.query(models.Shoe)
            .filter(
                models.Shoe.id == shoe_id,
                models.Shoe.user_id == user_id,
                models.Shoe.is_deleted.is_(False),
            )
            .first()
        )
        if not shoe:
            raise NotFound("Shoe not found")
        update_data = payload.model_dump(exclude_unset=True)
        supplied_version = update_data.pop("expected_version", None)
        current_version = int(getattr(shoe, "version", 0))
        if supplied_version is not None and supplied_version != current_version:
            raise Conflict("鞋款已被更新，請重新載入後再編輯")
        expected_version = current_version
        if "mileage" in update_data:
            logged_mileage = (
                db.query(func.sum(models.Run.km))
                .filter(models.Run.user_id == user_id, models.Run.shoe_id == shoe_id)
                .scalar()
            )
            logged_total = round(float(logged_mileage or 0), 2)
            if float(update_data["mileage"]) + 0.005 < logged_total:
                raise Invalid(f"總里程不可低於逐筆跑步日誌合計 {logged_total:.2f} km")
            update_data["baseline_mileage"] = round(float(update_data["mileage"]) - logged_total, 2)
        query = db.query(models.Shoe).filter(
            models.Shoe.id == shoe_id,
            models.Shoe.user_id == user_id,
            models.Shoe.is_deleted.is_(False),
        )
        query = query.filter(models.Shoe.version == expected_version)
        update_data["version"] = models.Shoe.version + 1
        changed = query.update(
            {getattr(models.Shoe, key): value for key, value in update_data.items()},
            synchronize_session=False,
        )
        if not changed:
            raise Conflict("鞋款已被更新，請重新載入後再編輯")
        return shoe


def delete_shoe(db: Session, user_id: int, shoe_id: int, expected_version: int | None = None):
    with write_transaction(db, user_id, reason="shoe.delete"):
        shoe = (
            db.query(models.Shoe)
            .filter(
                models.Shoe.id == shoe_id,
                models.Shoe.user_id == user_id,
                models.Shoe.is_deleted.is_(False),
            )
            .first()
        )
        if not shoe:
            raise NotFound("Shoe not found")
        version = getattr(shoe, "version", 0) if expected_version is None else expected_version
        changed = (
            db.query(models.Shoe)
            .filter(
                models.Shoe.id == shoe_id,
                models.Shoe.user_id == user_id,
                models.Shoe.is_deleted.is_(False),
                models.Shoe.version == version,
            )
            .update(
                {models.Shoe.is_deleted: True, models.Shoe.version: models.Shoe.version + 1},
                synchronize_session=False,
            )
        )
        if not changed:
            raise Conflict("鞋款已被更新，請重新載入後再刪除")
        return {"ok": True}
