"""Strava CSV upload and import HTTP routes."""

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend import models, schemas, strava_import
from backend.auth import get_current_user
from backend.dependencies import get_db, get_settings
from backend.read_models.runs import recent_strava_imports
from backend.services import strava_imports
from backend.settings import Settings, megabytes_label

router = APIRouter(tags=["strava"])


def _parse_strava_csv(raw: bytes, max_rows: int) -> tuple[list[dict[str, object]], int, list[str]]:
    try:
        return strava_import.parse_csv(raw, max_rows=max_rows)
    except strava_import.InvalidCSVError as exc:
        raise HTTPException(status_code=413 if exc.row_limit else 400, detail=str(exc)) from exc


def _filter_strava_rows(
    rows: list[dict[str, object]], start_date: str, end_date: str
) -> tuple[list[dict[str, object]], int]:
    try:
        return strava_import.filter_rows(rows, start_date, end_date)
    except strava_import.InvalidCSVError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _read_strava_upload(file: UploadFile, max_bytes: int) -> bytes:
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"CSV 檔案不可超過 {megabytes_label(max_bytes)}")
    return raw


def _parsed_mapping(raw_mapping: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_mapping)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="鞋款配對格式錯誤") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="鞋款配對格式錯誤")
    return parsed


def _preview_upload(db: Session, user_id: int, raw: bytes, start_date: str, end_date: str, config: Settings):
    """One sequential worker owns CSV parsing and all request-session DB work."""
    rows, invalid, warnings = _parse_strava_csv(raw, config.max_strava_csv_rows)
    rows, filtered_out = _filter_strava_rows(rows, start_date, end_date)
    result = strava_imports.preview(db, user_id, rows, invalid, warnings)
    result["filtered_out"] = filtered_out
    return result


def _import_upload(db: Session, user_id: int, raw: bytes, mapping: str, start_date: str, end_date: str, config: Settings):
    parsed_mapping = _parsed_mapping(mapping)
    rows, invalid, _ = _parse_strava_csv(raw, config.max_strava_csv_rows)
    rows, filtered_out = _filter_strava_rows(rows, start_date, end_date)
    try:
        result = strava_imports.import_runs(
            db,
            user_id,
            rows,
            parsed_mapping,
            start_date=start_date,
            end_date=end_date,
            invalid=invalid,
            filtered_out=filtered_out,
            max_runs=config.max_runs_per_user,
            history_limit=config.max_strava_import_history_per_user,
        )
    except strava_imports.InvalidShoeMappingError as exc:
        if str(exc) == "ownership":
            raise HTTPException(
                status_code=404, detail="鞋款不存在或不屬於目前帳號"
            ) from exc
        raise HTTPException(status_code=400, detail="鞋款配對格式錯誤") from exc
    except strava_imports.RunQuotaExceededError as exc:
        raise HTTPException(status_code=409, detail="匯入後跑步紀錄將超過上限") from exc
    except strava_imports.DuplicateImportError as exc:
        raise HTTPException(
            status_code=409, detail="部分 Strava 活動已存在，請重新預覽"
        ) from exc
    return result.as_dict()


@router.post("/api/runs/import/strava/preview")
async def preview_strava_import(
    file: UploadFile = File(...),
    start_date: str = Form(""),
    end_date: str = Form(""),
    config: Settings = Depends(get_settings),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    raw = await _read_strava_upload(file, config.max_strava_csv_bytes)
    return await run_in_threadpool(_preview_upload, db, user_id, raw, start_date, end_date, config)


@router.post("/api/runs/import/strava")
async def import_strava_runs(
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    config: Settings = Depends(get_settings),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    raw = await _read_strava_upload(file, config.max_strava_csv_bytes)
    return await run_in_threadpool(_import_upload, db, user_id, raw, mapping, start_date, end_date, config)


@router.get("/api/runs/import/strava/history", response_model=list[schemas.StravaImportOut])
def list_strava_imports(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return recent_strava_imports(db, current_user.id)
