"""Pure parsing and preview helpers for Strava CSV imports."""

import csv
import io
import math
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime

from backend import schemas
from backend.clock import APP_TIMEZONE
from backend.run_metrics import is_plausible_duration


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
    # Optional (SPEC-060). Moving time matches the pace Strava shows for runs;
    # elapsed time is the fallback for exports without it. Both are in seconds.
    "moving_time": ("移動時間", "Moving Time"),
    "elapsed_time": ("經過時間", "Elapsed Time"),
}
STRAVA_REQUIRED_FIELDS = {"id", "date", "type", "gear", "distance"}
STRAVA_RUN_TYPES = {"跑步", "Run", "TrailRun", "Trail Run", "VirtualRun", "Virtual Run"}


def _field(headers: Sequence[str], key: str) -> str | None:
    return next((candidate for candidate in STRAVA_HEADERS[key] if candidate in headers), None)


_CHINESE_DATE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
_CHINESE_TIME = re.compile(r"(上午|下午)\s*(\d{1,2}):(\d{2}):(\d{2})")
_TIMESTAMP_FORMATS = ("%b %d, %Y, %I:%M:%S %p", "%B %d, %Y, %I:%M:%S %p")
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y")
_SHORT_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y")


def _utc_timestamp(text_value: str) -> datetime | None:
    """A Strava export timestamp, which is written in UTC, or None without a time."""
    day = _CHINESE_DATE.search(text_value)
    clock = _CHINESE_TIME.search(text_value)
    if day and clock:
        hour = int(clock.group(2)) % 12 + (12 if clock.group(1) == "下午" else 0)
        return datetime(int(day.group(1)), int(day.group(2)), int(day.group(3)), hour,
                        int(clock.group(3)), int(clock.group(4)), tzinfo=UTC)
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text_value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _calendar_date(text_value: str) -> date:
    day = _CHINESE_DATE.search(text_value)
    if day:
        return date(int(day.group(1)), int(day.group(2)), int(day.group(3)))
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text_value, fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    for fmt in _SHORT_DATE_FORMATS:
        try:
            return datetime.strptime(text_value[:10], fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    raise ValueError("invalid date")


def parse_activity_dates(value: str) -> tuple[str, str]:
    """Return (application calendar date, UTC calendar date) for one activity.

    Strava's bulk export writes Activity Date in UTC: a 06:00 run in Taipei is
    22:00 UTC on the previous day. The run belongs to the local calendar day.
    The UTC date is what versions before SPEC-047 stored, and identifies runs
    that a re-import may correct. A value without a time is used as-is.
    """
    text_value = value.strip()
    stamp = _utc_timestamp(text_value)
    if stamp is not None:
        return stamp.astimezone(APP_TIMEZONE).date().isoformat(), stamp.date().isoformat()
    day = _calendar_date(text_value).isoformat()
    return day, day


def parse_duration_seconds(value: str | None, km: float) -> int | None:
    """Whole seconds from a Strava time column, or None when absent or implausible.

    A missing or unusable time never rejects the activity: the run is still
    imported with its distance, only without a pace.
    """
    try:
        seconds = float((value or "").replace(",", "").strip())
    except ValueError:
        return None
    if not math.isfinite(seconds):
        return None
    duration = round(seconds)
    return duration if is_plausible_duration(duration, km) else None


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
                date_value, utc_date = parse_activity_dates(row.get(fields["date"] or "") or "")
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
            duration = parse_duration_seconds(row.get(fields["moving_time"] or ""), km)
            if duration is None:
                duration = parse_duration_seconds(row.get(fields["elapsed_time"] or ""), km)
            rows.append({
                "strava_id": activity_id[:100],
                "duration_seconds": duration,
                "date": date_value,
                "utc_date": utc_date,
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


def date_corrections(
    rows: list[dict[str, object]], existing_dates: dict[str, str]
) -> list[dict[str, object]]:
    """Existing runs still stored on the UTC date that pre-SPEC-047 imports used.

    Only a run whose stored date equals the activity's UTC date (and differs from
    its local date) is corrected, so a date the user edited by hand is kept.
    """
    corrections: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        strava_id = str(row["strava_id"])
        if strava_id in seen or strava_id not in existing_dates:
            continue
        seen.add(strava_id)
        local, utc = str(row["date"]), str(row.get("utc_date", row["date"]))
        if local != utc and existing_dates[strava_id] == utc:
            corrections.append({"strava_id": strava_id, "from_date": utc, "to_date": local, "km": row["km"]})
    return corrections


def duration_backfills(
    rows: list[dict[str, object]], existing: dict[str, tuple[int | None, float]]
) -> list[dict[str, object]]:
    """Existing Strava runs that have no moving time yet and get one from this CSV (SPEC-060).

    `existing` maps a stored run's Strava ID to its (duration_seconds, km). A stored
    time is never overwritten, and a time that gives an implausible pace for the
    stored distance (edited by hand after an earlier import) is skipped.
    """
    backfills: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        strava_id = str(row["strava_id"])
        duration = row.get("duration_seconds")
        if strava_id in seen or strava_id not in existing or not isinstance(duration, int):
            continue
        seen.add(strava_id)
        stored_duration, km = existing[strava_id]
        if stored_duration is None and is_plausible_duration(duration, km):
            backfills.append({"strava_id": strava_id, "duration_seconds": duration})
    return backfills
