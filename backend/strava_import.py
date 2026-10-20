"""Pure parsing and preview helpers for Strava CSV imports."""

import csv
import io
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from backend import schemas


class InvalidCSVError(ValueError):
    """Invalid CSV or date range; HTTP mapping belongs to the router."""

    def __init__(self, message: str, *, row_limit: int | None = None):
        super().__init__(message)
        self.row_limit = row_limit


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
        raise InvalidCSVError("無法讀取 CSV，請使用 UTF-8 編碼") from exc
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    fields = {key: _field(headers, key) for key in STRAVA_HEADERS}
    missing = [key for key in STRAVA_REQUIRED_FIELDS if fields[key] is None]
    if missing:
        raise InvalidCSVError("CSV 缺少必要欄位：" + ", ".join(missing))
    rows: list[dict[str, object]] = []
    invalid = 0
    warnings: list[str] = []
    try:
        for row_number, row in enumerate(reader, start=1):
            if row_number > max_rows:
                raise InvalidCSVError(f"CSV 資料列不可超過 {max_rows:,} 筆", row_limit=max_rows)
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
        raise InvalidCSVError("CSV 格式錯誤") from exc
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
            raise InvalidCSVError(f"{label}日期格式錯誤") from exc
    normalized_start, normalized_end = normalized_dates
    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise InvalidCSVError("起始日期不可晚於結束日期")
    filtered = [
        row for row in rows
        if (not normalized_start or str(row["date"]) >= normalized_start)
        and (not normalized_end or str(row["date"]) <= normalized_end)
    ]
    return filtered, len(rows) - len(filtered)
