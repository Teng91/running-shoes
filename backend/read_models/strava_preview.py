"""User-scoped CSV matching preview, independent of transport."""

from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session

from backend import models
from backend.read_models.rounding import round_metric
from backend.strava_import import (
    date_corrections,
    duration_backfills,
    manual_matches,
    normalize_gear,
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


def deleted_strava_ids(db: Session, user_id: int) -> set[str]:
    """Strava activities this account deleted; a CSV re-import must not recreate them."""
    rows = db.query(models.RunTombstone.strava_id).filter(
        models.RunTombstone.user_id == user_id, models.RunTombstone.strava_id.isnot(None),
    )
    return {strava_id for (strava_id,) in rows if strava_id}


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
        key = normalize_gear(f"{shoe.brand} {shoe.model}")
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
        group["km"] = round_metric(float(cast(float, group["km"])) + float(cast(float, row["km"])), 2)
    # SPEC-092: a conflict the user imports needs a shoe, so its gear always gets a group;
    # conflict_count says how many of the group's activities wait for that choice.
    for conflict in conflicts:
        gear = str(conflict["gear"])
        group = groups.setdefault(gear, {"gear": gear, "count": 0, "km": 0.0, "first_date": str(conflict["date"])})
        group["first_date"] = min(str(group["first_date"]), str(conflict["date"]))
        group["conflict_count"] = int(cast(int, group.get("conflict_count", 0))) + 1
    for group in groups.values():
        group.setdefault("conflict_count", 0)
        candidates = shoes_by_key.get(normalize_gear(str(group["gear"])), [])
        suggested_shoe = candidates[0] if len(candidates) == 1 else None
        group["suggested_shoe_id"] = suggested_shoe.id if suggested_shoe else None
        group["shoe_name"] = (
            f"{suggested_shoe.brand} {suggested_shoe.model}" if suggested_shoe else None
        )
        group["ambiguous_match"] = len(candidates) > 1
    corrections = date_corrections(rows, existing_dates)
    candidate_ids = {run_id for conflict in conflicts for run_id in cast(list[int], conflict["candidate_run_ids"])}
    conflict_candidates = {
        row.id: {"run_id": row.id, "km": float(row.km), "duration_seconds": row.duration_seconds,
                 "shoe_name": f"{row.brand} {row.model}".strip() if row.brand else None}
        for row in db.query(models.Run.id, models.Run.km, models.Run.duration_seconds, models.Shoe.brand, models.Shoe.model)
        .outerjoin(models.Shoe, (models.Shoe.id == models.Run.shoe_id) & (models.Shoe.user_id == user_id))
        .filter(models.Run.user_id == user_id, models.Run.id.in_(candidate_ids))
    } if candidate_ids else {}
    return {
        "total_rows": len(rows) + invalid,
        "run_count": len(rows),
        "importable_count": len(rows) - duplicate_count - deleted_count - len(manual_ids),
        "importable_km": round_metric(importable_km, 2),
        "duplicate_count": duplicate_count,
        "deleted_count": deleted_count,
        "date_correction_count": len(corrections),
        "date_correction_samples": corrections[:5],
        "duration_backfill_count": len(backfills),
        # SPEC-062: activities already entered by hand are linked, never imported twice.
        "manual_link_count": len(links),
        "manual_link_duration_count": sum(link["duration_seconds"] is not None for link in links),
        "manual_conflict_count": len(conflicts),
        "manual_conflict_samples": [
            {key: conflict[key] for key in ("strava_id", "date", "km")} for conflict in conflicts[:5]
        ],
        # SPEC-091: the user picks skip, link or import for each conflict.
        "manual_conflicts": [
            {"strava_id": conflict["strava_id"], "date": conflict["date"], "km": conflict["km"],
             "duration_seconds": conflict["duration_seconds"], "gear": conflict["gear"],
             "candidates": [conflict_candidates[run_id] for run_id in cast(list[int], conflict["candidate_run_ids"])
                            if run_id in conflict_candidates]}
            for conflict in conflicts
        ],
        "invalid_count": invalid,
        "gear_groups": sorted(groups.values(), key=lambda group: str(group["gear"])),
        "warnings": warnings,
    }
