"""User-scoped CSV matching preview, independent of transport."""

from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session

from backend import models
from backend.services.run_identity import deleted_strava_ids
from backend.strava_import import (
    _normalize_gear,
    date_corrections,
    duration_backfills,
    manual_matches,
)


@dataclass(frozen=True)
class StoredRuns:
    """The user's runs a Strava CSV is matched against (shared by preview and import)."""

    strava: dict[str, tuple[str, int | None, float]]
    manual: list[tuple[int, str, float, int | None]]
    deleted_ids: set[str]

    @property
    def existing_dates(self) -> dict[str, str]:
        return {strava_id: run[0] for strava_id, run in self.strava.items()}

    @property
    def durations(self) -> dict[str, tuple[int | None, float]]:
        return {strava_id: (run[1], run[2]) for strava_id, run in self.strava.items()}

    def manual_matches(
        self, rows: list[dict[str, object]]
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return manual_matches(rows, self.manual, set(self.strava) | self.deleted_ids)


def stored_runs(db: Session, user_id: int) -> StoredRuns:
    strava: dict[str, tuple[str, int | None, float]] = {}
    manual: list[tuple[int, str, float, int | None]] = []
    for row in db.query(
        models.Run.id, models.Run.strava_id, models.Run.date, models.Run.duration_seconds, models.Run.km
    ).filter(models.Run.user_id == user_id):
        if row.strava_id is None:
            manual.append((row.id, row.date, float(row.km), row.duration_seconds))
        else:
            strava[row.strava_id] = (row.date, row.duration_seconds, float(row.km))
    return StoredRuns(strava, manual, deleted_strava_ids(db, user_id))


def build_preview(
    db: Session,
    user_id: int,
    rows: list[dict[str, object]],
    invalid: int,
    warnings: list[str],
) -> dict[str, object]:
    stored = stored_runs(db, user_id)
    existing_dates = stored.existing_dates
    backfills = duration_backfills(rows, stored.durations)
    existing_ids = set(existing_dates)
    deleted_ids = stored.deleted_ids
    links, conflicts = stored.manual_matches(rows)
    manual_ids = {str(item["strava_id"]) for item in links + conflicts}
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
    deleted_count = 0
    importable_km = 0.0
    for row in rows:
        strava_id = str(row["strava_id"])
        if strava_id in existing_ids or strava_id in seen:
            duplicate_count += 1
            continue
        seen.add(strava_id)
        if strava_id in deleted_ids:
            deleted_count += 1
            continue
        if strava_id in manual_ids:
            continue
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
    corrections = date_corrections(rows, existing_dates)
    return {
        "total_rows": len(rows) + invalid,
        "run_count": len(rows),
        "importable_count": len(rows) - duplicate_count - deleted_count - len(manual_ids),
        "importable_km": round(importable_km, 2),
        "duplicate_count": duplicate_count,
        "deleted_count": deleted_count,
        "date_correction_count": len(corrections),
        "date_correction_samples": corrections[:5],
        "duration_backfill_count": len(backfills),
        # SPEC-062: activities already entered by hand are linked, never imported twice.
        "manual_link_count": len(links),
        "manual_link_duration_count": sum(link["duration_seconds"] is not None for link in links),
        "manual_conflict_count": len(conflicts),
        "manual_conflict_samples": conflicts[:5],
        "invalid_count": invalid,
        "gear_groups": sorted(groups.values(), key=lambda group: str(group["gear"])),
        "warnings": warnings,
    }
