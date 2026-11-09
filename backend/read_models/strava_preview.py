"""User-scoped CSV matching preview, independent of transport."""

from typing import cast

from sqlalchemy.orm import Session

from backend import models
from backend.strava_import import _normalize_gear


def build_preview(
    db: Session,
    user_id: int,
    rows: list[dict[str, object]],
    invalid: int,
    warnings: list[str],
) -> dict[str, object]:
    existing_ids = {
        value[0]
        for value in db.query(models.Run.strava_id)
        .filter(models.Run.user_id == user_id, models.Run.strava_id.isnot(None))
        .all()
    }
    shoes = (
        db.query(models.Shoe)
        .filter(
            models.Shoe.user_id == user_id,
            models.Shoe.is_deleted.is_(False),
        )
        .all()
    )
    shoes_by_key: dict[str, list[models.Shoe]] = {}
    for shoe in shoes:
        key = _normalize_gear(f"{shoe.brand} {shoe.model}")
        if key:
            shoes_by_key.setdefault(key, []).append(shoe)
    groups: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    duplicate_count = 0
    importable_km = 0.0
    for row in rows:
        strava_id = str(row["strava_id"])
        if strava_id in existing_ids or strava_id in seen:
            duplicate_count += 1
            continue
        seen.add(strava_id)
        importable_km += float(cast(float, row["km"]))
        gear = str(row["gear"])
        group = groups.setdefault(
            gear, {"gear": gear, "count": 0, "km": 0.0, "first_date": str(row["date"])}
        )
        group["first_date"] = min(str(group["first_date"]), str(row["date"]))
        group["count"] = int(cast(int, group["count"])) + 1
        group["km"] = round(float(cast(float, group["km"])) + float(cast(float, row["km"])), 2)
    for group in groups.values():
        candidates = shoes_by_key.get(_normalize_gear(str(group["gear"])), [])
        suggested_shoe = candidates[0] if len(candidates) == 1 else None
        group["suggested_shoe_id"] = suggested_shoe.id if suggested_shoe else None
        group["shoe_name"] = (
            f"{suggested_shoe.brand} {suggested_shoe.model}" if suggested_shoe else None
        )
        group["ambiguous_match"] = len(candidates) > 1
    return {
        "total_rows": len(rows) + invalid,
        "run_count": len(rows),
        "importable_count": len(rows) - duplicate_count,
        "importable_km": round(importable_km, 2),
        "duplicate_count": duplicate_count,
        "invalid_count": invalid,
        "gear_groups": sorted(groups.values(), key=lambda group: str(group["gear"])),
        "warnings": warnings,
    }
