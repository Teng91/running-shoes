"""Optional development seed data, isolated from application composition."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from backend import models
from backend.credentials import get_password_hash
from backend.settings import Settings


def seed_default_data(session_factory: Callable[[], Session], config: Settings) -> None:
    if not config.seed_data:
        return
    db = session_factory()
    try:
        joy_user = db.query(models.User).filter(models.User.username == "Joy").first()
        if not joy_user:
            if not config.migration_password:
                raise RuntimeError(
                    "MIGRATION_PASSWORD must be set when SEED_DATA=true so the "
                    "Joy account has a known password."
                )
            joy_user = models.User(
                username="Joy",
                hashed_password=get_password_hash(config.migration_password),
            )
            db.add(joy_user)
            db.commit()
            db.refresh(joy_user)
        if db.query(models.Shoe).count() == 0:
            # Fictional sample shoes (SPEC-081): no real purchases, sizes or prices.
            defaults = [
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Rider", date="2025-03-01", size="us10/28cm", price=3000, orig_price=4500, mileage=520, expected_mileage=800, monthly_km=60, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="ASICS", model="Novablast", date="2025-09-01", size="us10/28cm", price=3200, orig_price=4200, mileage=280, expected_mileage=800, monthly_km=60, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="Hoka", model="Clifton", date="2026-01-10", size="us10/28cm", price=3500, orig_price=4800, mileage=120, expected_mileage=800, monthly_km=50, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="Saucony", model="Kinvara", date="2026-02-01", size="us10/28cm", price=2800, orig_price=3900, mileage=100, expected_mileage=500, monthly_km=30, categories=["Speed"]),
                models.Shoe(user_id=joy_user.id, brand="Adidas", model="Adizero SL", date="2026-03-15", size="us10/28cm", price=2500, orig_price=3800, mileage=60, expected_mileage=800, monthly_km=30, categories=["Tempo"]),
                models.Shoe(user_id=joy_user.id, brand="Nike", model="Vaporfly", date="2026-05-20", size="us10/28cm", price=6000, orig_price=8000, mileage=0, expected_mileage=500, monthly_km=20, categories=["Race"]),
                models.Shoe(user_id=joy_user.id, brand="Brooks", model="Ghost", date="2024-06-01", size="us10/28cm", price=2600, orig_price=4300, mileage=650, expected_mileage=600, monthly_km=0, is_retired=True, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="New Balance", model="Fresh Foam", date="2024-11-01", size="us10/28cm", price=2400, orig_price=3600, mileage=420, expected_mileage=400, monthly_km=0, is_retired=True, categories=["Daily"]),
            ]
            for shoe in defaults:
                shoe.baseline_mileage = shoe.mileage
            db.add_all(defaults)
            db.commit()
        if db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.user_id == joy_user.id
        ).count() == 0:
            # Fictional, steadily growing monthly mileage from mid-2024 (SPEC-081).
            mileage_data = [
                (year, month, round(30 + index * 4 + (index % 3) * 5.5, 2))
                for index, (year, month) in enumerate(
                    [(2024, m) for m in range(6, 13)] + [(2025, m) for m in range(1, 13)]
                    + [(2026, m) for m in range(1, 7)]
                )
            ]
            db.add_all([
                models.MonthlyMileage(
                    user_id=joy_user.id, year=year, month=month, km=km, adjustment_km=km
                )
                for year, month, km in mileage_data
            ])
            db.commit()
    finally:
        db.close()
