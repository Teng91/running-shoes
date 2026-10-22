"""Transactional Strava import orchestration independent of FastAPI."""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import models
from backend.read_models.strava_preview import build_preview
from backend.services.mileage import apply_run_mileage_deltas
from backend.services.transactions import write_transaction


class InvalidShoeMappingError(Exception):
    """Raised when a mapped shoe is invalid or belongs to another user."""


class RunQuotaExceededError(Exception):
    """Raised when an import would exceed the per-user run limit."""


class DuplicateImportError(Exception):
    """Raised when concurrent imports include the same Strava activity."""


@dataclass(frozen=True)
class ImportResult:
    imported: int
    skipped_duplicate: int
    skipped_unmapped: int
    skipped_invalid: int
    filtered_out: int
    synced_mileage: float
    total_run_rows: int

    def as_dict(self) -> dict[str, int | float]:
        return {
            "imported": self.imported,
            "skipped_duplicate": self.skipped_duplicate,
            "skipped_unmapped": self.skipped_unmapped,
            "skipped_invalid": self.skipped_invalid,
            "filtered_out": self.filtered_out,
            "synced_mileage": round(self.synced_mileage, 2),
            "total_run_rows": self.total_run_rows,
        }


def preview(
    db: Session,
    user_id: int,
    rows: list[dict[str, object]],
    invalid: int,
    warnings: list[str],
) -> dict[str, object]:
    return build_preview(db, user_id, rows, invalid, warnings)


def import_runs(
    db: Session,
    user_id: int,
    rows: list[dict[str, object]],
    mapping: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    invalid: int,
    filtered_out: int,
    max_runs: int,
    history_limit: int,
) -> ImportResult:
    """Validate, persist, and mileage-sync a user-scoped Strava import."""
    with write_transaction(db, user_id):
        normalized_mapping = _normalize_mapping(db, user_id, mapping)
        existing_ids = {
            value[0]
            for value in db.query(models.Run.strava_id)
            .filter(
                models.Run.user_id == user_id,
                models.Run.strava_id.isnot(None),
            )
            .all()
        }
        runs, duplicate_count, unmapped_count = _prepare_runs(
            rows, user_id, normalized_mapping, existing_ids
        )
        current_count = db.query(models.Run).filter(models.Run.user_id == user_id).count()
        if current_count + len(runs) > max_runs:
            raise RunQuotaExceededError

        synced_mileage = apply_run_mileage_deltas(
            db,
            user_id,
            [(run.shoe_id, run.date, run.km) for run in runs],
            1,
        )
        db.add_all(runs)
        db.add(
            models.StravaImport(
                user_id=user_id,
                start_date=start_date,
                end_date=end_date,
                imported_count=len(runs),
                imported_km=synced_mileage,
                duplicate_count=duplicate_count,
                unmapped_count=unmapped_count,
                invalid_count=invalid,
            )
        )
        try:
            db.flush()
            _trim_history(db, user_id, history_limit)
        except IntegrityError as exc:
            raise DuplicateImportError from exc
        except Exception:
            raise
        return ImportResult(
            imported=len(runs),
            skipped_duplicate=duplicate_count,
            skipped_unmapped=unmapped_count,
            skipped_invalid=invalid,
            filtered_out=filtered_out,
            synced_mileage=synced_mileage,
            total_run_rows=len(rows),
        )


def _normalize_mapping(db: Session, user_id: int, mapping: dict[str, Any]) -> dict[str, int | None]:
    shoe_ids = {
        shoe_id
        for (shoe_id,) in db.query(models.Shoe.id)
        .filter(
            models.Shoe.user_id == user_id,
            models.Shoe.is_deleted.is_(False),
        )
        .all()
    }
    normalized: dict[str, int | None] = {}
    for gear, shoe_id in mapping.items():
        if shoe_id in (None, "", 0, "0"):
            normalized[str(gear)] = None
            continue
        try:
            shoe_id_int = int(shoe_id)
        except (TypeError, ValueError) as exc:
            raise InvalidShoeMappingError("format") from exc
        if shoe_id_int not in shoe_ids:
            raise InvalidShoeMappingError("ownership")
        normalized[str(gear)] = shoe_id_int
    return normalized


def _prepare_runs(
    rows: list[dict[str, object]],
    user_id: int,
    mapping: dict[str, int | None],
    existing_ids: set[str],
) -> tuple[list[models.Run], int, int]:
    seen: set[str] = set()
    runs: list[models.Run] = []
    duplicate_count = 0
    unmapped_count = 0
    for row in rows:
        strava_id = str(row["strava_id"])
        if strava_id in existing_ids or strava_id in seen:
            duplicate_count += 1
            continue
        seen.add(strava_id)
        shoe_id = mapping.get(str(row["gear"]))
        if shoe_id is None:
            unmapped_count += 1
            continue
        runs.append(
            models.Run(
                user_id=user_id,
                shoe_id=shoe_id,
                date=str(row["date"]),
                km=float(cast(float | str, row["km"])),
                strava_id=strava_id,
            )
        )
    return runs, duplicate_count, unmapped_count


def _trim_history(db: Session, user_id: int, history_limit: int) -> None:
    stale_ids = [
        value[0]
        for value in db.query(models.StravaImport.id)
        .filter(
            models.StravaImport.user_id == user_id,
        )
        .order_by(
            models.StravaImport.imported_at.desc(),
            models.StravaImport.id.desc(),
        )
        .offset(history_limit)
        .all()
    ]
    if stale_ids:
        db.query(models.StravaImport).filter(
            models.StravaImport.user_id == user_id,
            models.StravaImport.id.in_(stale_ids),
        ).delete(synchronize_session=False)
