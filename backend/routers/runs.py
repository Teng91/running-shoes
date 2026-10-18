"""Run log and Strava import HTTP routes."""

import json
from calendar import monthrange
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import models, schemas, strava_import
from backend.auth import get_current_user
from backend.database import get_db
from backend.services.mileage import apply_run_mileage_deltas
from backend.settings import settings

router = APIRouter(tags=["runs"])
MAX_RUNS_PER_USER = settings.max_runs_per_user
MAX_STRAVA_CSV_BYTES = settings.max_strava_csv_bytes
MAX_STRAVA_CSV_ROWS = settings.max_strava_csv_rows
MAX_STRAVA_IMPORT_HISTORY_PER_USER = settings.max_strava_import_history_per_user


def _user_shoe_or_404(db: Session, user_id: int, shoe_id: int) -> models.Shoe:
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    return shoe


def _parse_strava_csv(raw: bytes) -> tuple[list[dict[str, object]], int, list[str]]:
    return strava_import.parse_csv(raw, max_rows=MAX_STRAVA_CSV_ROWS)


def _filter_strava_rows(
    rows: list[dict[str, object]], start_date: str, end_date: str
) -> tuple[list[dict[str, object]], int]:
    return strava_import.filter_rows(rows, start_date, end_date)


async def _read_strava_upload(file: UploadFile) -> bytes:
    raw = await file.read(MAX_STRAVA_CSV_BYTES + 1)
    if len(raw) > MAX_STRAVA_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV 檔案不可超過 10 MB")
    return raw


def _strava_preview(
    db: Session,
    user_id: int,
    rows: list[dict[str, object]],
    invalid: int,
    warnings: list[str],
) -> dict[str, object]:
    return strava_import.build_preview(db, user_id, rows, invalid, warnings)


@router.post("/api/runs/import/strava/preview")
async def preview_strava_import(
    file: UploadFile = File(...),
    start_date: str = Form(""),
    end_date: str = Form(""),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = await _read_strava_upload(file)
    rows, invalid, warnings = _parse_strava_csv(raw)
    rows, filtered_out = _filter_strava_rows(rows, start_date, end_date)
    preview = _strava_preview(db, current_user.id, rows, invalid, warnings)
    preview["filtered_out"] = filtered_out
    return preview


@router.post("/api/runs/import/strava")
async def import_strava_runs(
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        parsed_mapping = json.loads(mapping)
        if not isinstance(parsed_mapping, dict):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="鞋款配對格式錯誤") from exc
    raw = await _read_strava_upload(file)
    rows, invalid, _ = _parse_strava_csv(raw)
    rows, filtered_out = _filter_strava_rows(rows, start_date, end_date)
    shoes = {shoe.id: shoe for shoe in db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).all()}
    normalized_mapping: dict[str, int | None] = {}
    for gear, shoe_id in parsed_mapping.items():
        if shoe_id in (None, "", 0, "0"):
            normalized_mapping[str(gear)] = None
            continue
        try:
            shoe_id_int = int(cast(str | int, shoe_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="鞋款配對格式錯誤") from exc
        if shoe_id_int not in shoes:
            raise HTTPException(status_code=404, detail="鞋款不存在或不屬於目前帳號")
        normalized_mapping[str(gear)] = shoe_id_int
    existing_ids = {
        value[0] for value in db.query(models.Run.strava_id).filter(
            models.Run.user_id == current_user.id, models.Run.strava_id.isnot(None)
        ).all()
    }
    seen: set[str] = set()
    runs_to_add: list[models.Run] = []
    skipped_duplicate = 0
    skipped_unmapped = 0
    for row in rows:
        strava_id = str(row["strava_id"])
        if strava_id in existing_ids or strava_id in seen:
            skipped_duplicate += 1
            continue
        seen.add(strava_id)
        shoe_id = normalized_mapping.get(str(row["gear"]))
        if shoe_id is None:
            skipped_unmapped += 1
            continue
        runs_to_add.append(models.Run(
            user_id=current_user.id,
            shoe_id=shoe_id,
            date=str(row["date"]),
            km=float(cast(float, row["km"])),
            strava_id=strava_id,
        ))
    current_count = db.query(models.Run).filter(models.Run.user_id == current_user.id).count()
    if current_count + len(runs_to_add) > MAX_RUNS_PER_USER:
        raise HTTPException(status_code=409, detail="匯入後跑步紀錄將超過上限")
    synced_mileage = apply_run_mileage_deltas(
        db,
        current_user.id,
        [(run.shoe_id, run.date, run.km) for run in runs_to_add],
        1,
    )
    db.add_all(runs_to_add)
    import_record = models.StravaImport(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        imported_count=len(runs_to_add),
        imported_km=synced_mileage,
        duplicate_count=skipped_duplicate,
        unmapped_count=skipped_unmapped,
        invalid_count=invalid,
    )
    db.add(import_record)
    try:
        db.flush()
        stale_import_ids = [
            value[0] for value in db.query(models.StravaImport.id).filter(
                models.StravaImport.user_id == current_user.id,
            ).order_by(
                models.StravaImport.imported_at.desc(),
                models.StravaImport.id.desc(),
            ).offset(MAX_STRAVA_IMPORT_HISTORY_PER_USER).all()
        ]
        if stale_import_ids:
            db.query(models.StravaImport).filter(
                models.StravaImport.user_id == current_user.id,
                models.StravaImport.id.in_(stale_import_ids),
            ).delete(synchronize_session=False)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="部分 Strava 活動已存在，請重新預覽") from exc
    except Exception:
        db.rollback()
        raise
    return {
        "imported": len(runs_to_add),
        "skipped_duplicate": skipped_duplicate,
        "skipped_unmapped": skipped_unmapped,
        "skipped_invalid": invalid,
        "filtered_out": filtered_out,
        "synced_mileage": round(synced_mileage, 2),
        "total_run_rows": len(rows),
    }


@router.get("/api/runs/import/strava/history", response_model=list[schemas.StravaImportOut])
def list_strava_imports(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.StravaImport).filter(
        models.StravaImport.user_id == current_user.id,
    ).order_by(models.StravaImport.imported_at.desc(), models.StravaImport.id.desc()).limit(10).all()


@router.get("/api/runs", response_model=list[schemas.RunOut])
def list_runs(
    year: int | None = Query(default=None, ge=1900, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail="month requires year")
    query = db.query(models.Run).filter(models.Run.user_id == current_user.id)
    if year is not None:
        if month is None:
            start_date = f"{year:04d}-01-01"
            end_date = f"{year:04d}-12-31"
        else:
            last_day = monthrange(year, month)[1]
            start_date = f"{year:04d}-{month:02d}-01"
            end_date = f"{year:04d}-{month:02d}-{last_day:02d}"
        query = query.filter(
            models.Run.date >= start_date,
            models.Run.date <= end_date,
        )
    query = query.order_by(models.Run.date.desc(), models.Run.id.desc()).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


@router.post("/api/runs", response_model=schemas.RunOut)
def create_run(
    payload: schemas.RunCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _user_shoe_or_404(db, current_user.id, payload.shoe_id)
    run_count = db.query(models.Run).filter(models.Run.user_id == current_user.id).count()
    if isinstance(run_count, int) and run_count >= MAX_RUNS_PER_USER:
        raise HTTPException(status_code=409, detail="跑步紀錄已達上限")
    run = models.Run(**payload.model_dump(), user_id=current_user.id)
    db.add(run)
    try:
        apply_run_mileage_deltas(
            db,
            current_user.id,
            [(payload.shoe_id, payload.date, payload.km)],
            1,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run


@router.put("/api/runs/{run_id}", response_model=schemas.RunOut)
def update_run(
    run_id: int,
    payload: schemas.RunUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(models.Run).filter(
        models.Run.id == run_id,
        models.Run.user_id == current_user.id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    update_data = payload.model_dump(exclude_unset=True)
    expected_version = update_data.pop("expected_version", getattr(run, "version", 0))
    if "shoe_id" in update_data:
        _user_shoe_or_404(db, current_user.id, update_data["shoe_id"])
    old_values = (run.shoe_id, run.date, run.km)
    new_values = (
        int(update_data.get("shoe_id", run.shoe_id)),
        str(update_data.get("date", run.date)),
        float(update_data.get("km", run.km)),
    )
    try:
        changed = db.query(models.Run).filter(
            models.Run.id == run_id,
            models.Run.user_id == current_user.id,
            models.Run.version == expected_version,
        ).update(
            {
                **{
                    getattr(models.Run, key): value
                    for key, value in update_data.items()
                },
                models.Run.version: models.Run.version + 1,
            },
            synchronize_session=False,
        )
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="跑步紀錄已被更新，請重新載入後再編輯",
            )
        apply_run_mileage_deltas(
            db,
            current_user.id,
            [
                (old_values[0], old_values[1], -old_values[2]),
                new_values,
            ],
            1,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run


@router.delete("/api/runs/{run_id}")
def delete_run(
    run_id: int,
    expected_version: Annotated[int | None, Query(ge=0)] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(models.Run).filter(
        models.Run.id == run_id,
        models.Run.user_id == current_user.id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run_values = (run.shoe_id, run.date, run.km)
    version = getattr(run, "version", 0) if expected_version is None else expected_version
    try:
        changed = db.query(models.Run).filter(
            models.Run.id == run_id,
            models.Run.user_id == current_user.id,
            models.Run.version == version,
        ).delete(synchronize_session=False)
        if not changed:
            raise HTTPException(
                status_code=409,
                detail="跑步紀錄已被更新，請重新載入後再刪除",
            )
        apply_run_mileage_deltas(db, current_user.id, [run_values], -1)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}
