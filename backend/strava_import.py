"""Pure parsing and preview helpers for Strava CSV imports."""

import csv
import io
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend import models, schemas

STRAVA_HEADERS = {
    "id": ("活動 ID", "Activity ID"),
    "date": ("活動日期", "Activity Date"),
    "type": ("活動類型", "Activity Type"),
    "gear": ("活動裝備", "Activity Gear", "Gear"),
    "distance": ("距離", "Distance"),
}
STRAVA_REQUIRED_FIELDS = {"id", "date", "type", "gear", "distance"}
STRAVA_RUN_TYPES = {"跑步", "Run", "TrailRun", "Trail Run", "VirtualRun", "Virtual Run"}


def _field(headers: Sequence[str], key: str) -> str | None:
    return next((candidate for candidate in STRAVA_HEADERS[key] if candidate in headers), None)


def _parse_date(value: str) -> str:
    text_value = value.strip()
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text_value)
    if match:
        return datetime.strptime(
            f"{match.group(1)}-{match.group(2)}-{match.group(3)}", "%Y-%m-%d"
        ).replace(tzinfo=UTC).date().isoformat()
    for fmt in (
        "%b %d, %Y, %I:%M:%S %p",
        "%B %d, %Y, %I:%M:%S %p",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(text_value, fmt).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text_value[:10], fmt).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    raise ValueError("invalid date")


def _normalize_gear(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def parse_csv(
    raw: bytes,
    *,
    max_rows: int,
) -> tuple[list[dict[str, object]], int, list[str]]:
    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="無法讀取 CSV，請使用 UTF-8 編碼") from exc
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    fields = {key: _field(headers, key) for key in STRAVA_HEADERS}
    missing = [key for key in STRAVA_REQUIRED_FIELDS if fields[key] is None]
    if missing:
        raise HTTPException(status_code=400, detail="CSV 缺少必要欄位：" + ", ".join(missing))
    rows: list[dict[str, object]] = []
    invalid = 0
    warnings: list[str] = []
    try:
        for row_number, row in enumerate(reader, start=1):
            if row_number > max_rows:
                raise HTTPException(
                    status_code=413,
                    detail=f"CSV 資料列不可超過 {max_rows:,} 筆",
                )
            if (row.get(fields["type"] or "") or "").strip() not in STRAVA_RUN_TYPES:
                continue
            try:
                activity_id = (row.get(fields["id"] or "") or "").strip()
                date_value = _parse_date(row.get(fields["date"] or "") or "")
                schemas._validate_completed_run_date(date_value)
                distance_m = float((row.get(fields["distance"] or "") or "").replace(",", "").strip())
                km = round(distance_m / 1000, 2)
                if (
                    not activity_id
                    or not math.isfinite(distance_m)
                    or distance_m <= 0
                    or distance_m > 1_000_000
                    or km <= 0
                ):
                    raise ValueError("invalid activity")
            except (TypeError, ValueError):
                invalid += 1
                continue
            rows.append({
                "strava_id": activity_id[:100],
                "date": date_value,
                "km": km,
                "gear": (row.get(fields["gear"] or "") or "").strip(),
                "activity_type": (row.get(fields["type"] or "") or "").strip(),
            })
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail="CSV 格式錯誤") from exc
    if invalid:
        warnings.append(f"已略過 {invalid} 筆格式不完整的跑步活動")
    return rows, invalid, warnings


def filter_rows(
    rows: list[dict[str, object]], start_date: str, end_date: str
) -> tuple[list[dict[str, object]], int]:
    normalized_dates: list[str] = []
    for value, label in ((start_date, "起始"), (end_date, "結束")):
        if not value:
            normalized_dates.append("")
            continue
        try:
            normalized_dates.append(
                datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).date().isoformat()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{label}日期格式錯誤") from exc
    normalized_start, normalized_end = normalized_dates
    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise HTTPException(status_code=400, detail="起始日期不可晚於結束日期")
    filtered = [
        row for row in rows
        if (not normalized_start or str(row["date"]) >= normalized_start)
        and (not normalized_end or str(row["date"]) <= normalized_end)
    ]
    return filtered, len(rows) - len(filtered)


def build_preview(
    db: Session,
    user_id: int,
    rows: list[dict[str, object]],
    invalid: int,
    warnings: list[str],
) -> dict[str, object]:
    existing_ids = {
        value[0] for value in db.query(models.Run.strava_id).filter(
            models.Run.user_id == user_id, models.Run.strava_id.isnot(None)
        ).all()
    }
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
    ).all()
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
        group = groups.setdefault(gear, {"gear": gear, "count": 0, "km": 0.0})
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
