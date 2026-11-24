"""Pure parsing and preview helpers for Strava CSV imports."""

import csv
import io
import math
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import cast

from backend import schemas
from backend.clock import APP_TIMEZONE
from backend.run_metrics import counts_toward_training, is_plausible_duration


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
# Strava activity type -> run activity type (SPEC-096); other activities are skipped.
STRAVA_ACTIVITY_TYPES = {
    "跑步": "road", "Run": "road", "VirtualRun": "road", "Virtual Run": "road",
    "虛擬跑步": "road",
    "TrailRun": "trail", "Trail Run": "trail", "越野跑": "trail", "越野跑步": "trail",
    "Hike": "hike", "健行": "hike", "Walk": "walk", "步行": "walk",
}


def split_shoe_only(
    rows: list[dict[str, object]], include: bool
) -> tuple[list[dict[str, object]], int, float]:
    """Hikes and walks are imported only when the user opts in (SPEC-097).

    Before SPEC-096 they were skipped, so an account may already have added their
    kilometres to a shoe by hand; importing them silently would count them twice.
    Returns the rows to import, plus the count and distance of shoe-only rows.
    """
    shoe_only = [row for row in rows if not counts_toward_training(str(row.get("activity_type") or ""))]
    km = round(sum(float(cast(float, row["km"])) for row in shoe_only), 2)
    if include:
        return rows, len(shoe_only), km
    return [row for row in rows if counts_toward_training(str(row.get("activity_type") or ""))], len(shoe_only), km


def _field(headers: Sequence[str], key: str) -> str | None:
    return next((candidate for candidate in STRAVA_HEADERS[key] if candidate in headers), None)


_CHINESE_DATE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
# zh-TW exports name the part of the day instead of AM/PM: 凌晨, 清晨, 上午, 中午, 下午,
# 晚上 and so on (SPEC-063). Without a marker the hour is on a 24-hour clock.
_MORNING_MARKERS = ("午夜", "半夜", "凌晨", "清晨", "早上", "上午")
_AFTERNOON_MARKERS = ("下午", "傍晚", "晚上")
_CHINESE_TIME = re.compile(
    "(" + "|".join(_MORNING_MARKERS + _AFTERNOON_MARKERS + ("中午",)) + r")?\s*(\d{1,2}):(\d{2}):(\d{2})"
)
_TIMESTAMP_FORMATS = ("%b %d, %Y, %I:%M:%S %p", "%B %d, %Y, %I:%M:%S %p")
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y")
_SHORT_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y")


def _chinese_hour(marker: str | None, hour: int) -> int:
    if marker is None:
        return hour
    if marker == "中午":  # 中午12:40 is 12:40, 中午1:10 is 13:10
        return hour if hour >= 11 else hour + 12
    return hour % 12 + (12 if marker in _AFTERNOON_MARKERS else 0)


def _utc_timestamp(text_value: str) -> datetime | None:
    """A Strava export timestamp, which is written in UTC, or None without a time."""
    day = _CHINESE_DATE.search(text_value)
    clock = _CHINESE_TIME.search(text_value)
    if day and clock:
        hour = _chinese_hour(clock.group(1), int(clock.group(2)))
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
            activity_type = STRAVA_ACTIVITY_TYPES.get((row.get(fields["type"] or "") or "").strip())
            if activity_type is None:
                continue
            parsed = _activity_row(row, fields, activity_type)
            if parsed is None:
                invalid += 1
            else:
                rows.append(parsed)
    except csv.Error as exc:
        raise InvalidCSVError("CSV 格式錯誤") from exc
    if invalid:
        warnings.append(f"已略過 {invalid} 筆格式不完整的跑步活動")
    return rows, invalid, warnings


def _activity_row(row: dict, fields: dict[str, str | None], activity_type: str) -> dict[str, object] | None:
    """One supported activity as a run row, or None when its ID, date or distance is unusable."""
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
        return None
    duration = parse_duration_seconds(row.get(fields["moving_time"] or ""), km)
    if duration is None:
        duration = parse_duration_seconds(row.get(fields["elapsed_time"] or ""), km)
    return {
        "strava_id": activity_id[:100],
        "duration_seconds": duration,
        "date": date_value,
        "utc_date": utc_date,
        "km": km,
        "gear": (row.get(fields["gear"] or "") or "").strip(),
        "activity_type": activity_type,
    }


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


# SPEC-062: a Strava activity on the same local day as a hand-entered run is the same
# run when their distances are within max(0.3 km, 5%). Hand-entered distances are often
# rounded, and a same-day run outside the tolerance is skipped rather than imported.
MANUAL_MATCH_MIN_KM = 0.3
MANUAL_MATCH_RATIO = 0.05


def _close_km(first: float, second: float) -> bool:
    return abs(first - second) <= max(MANUAL_MATCH_MIN_KM, MANUAL_MATCH_RATIO * max(first, second))


def manual_matches(
    rows: list[dict[str, object]],
    manual_runs: Sequence[tuple[int, str, float, int | None]],
    known_ids: set[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Pair new Strava activities with hand-entered runs so a re-import never doubles them.

    `manual_runs` holds the user's runs without a Strava ID as (id, date, km, duration_seconds);
    `known_ids` are Strava IDs already stored or deleted, which are handled elsewhere. An
    activity links to a manual run only when each is the other's single close-distance
    candidate that day. Any other activity on a day with a manual run is a conflict: it is
    neither imported nor linked. A link carries the moving time only when the manual run has
    none and the time gives a plausible pace for the manual distance.
    """
    manual_by_date: dict[str, list[tuple[int, str, float, int | None]]] = {}
    for manual in manual_runs:
        manual_by_date.setdefault(manual[1], []).append(manual)
    new_by_date: dict[str, list[dict[str, object]]] = {}
    seen: set[str] = set()
    for row in rows:
        strava_id = str(row["strava_id"])
        if strava_id in known_ids or strava_id in seen:
            continue
        seen.add(strava_id)
        if str(row["date"]) in manual_by_date:
            new_by_date.setdefault(str(row["date"]), []).append(row)
    links: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    for day, activities in new_by_date.items():
        for row in activities:
            km = float(str(row["km"]))
            close = [manual for manual in manual_by_date[day] if _close_km(km, manual[2])]
            partner = close[0] if len(close) == 1 else None
            if partner is not None and sum(
                _close_km(float(str(other["km"])), partner[2]) for other in activities
            ) == 1:
                duration = row.get("duration_seconds")
                fill = (
                    duration
                    if partner[3] is None and isinstance(duration, int)
                    and is_plausible_duration(duration, partner[2])
                    else None
                )
                links.append({"strava_id": str(row["strava_id"]), "run_id": partner[0],
                              "date": day, "duration_seconds": fill})
                continue
            conflicts.append({"strava_id": str(row["strava_id"]), "date": day, "km": km,
                              "duration_seconds": row.get("duration_seconds"), "gear": str(row.get("gear") or "")})
    # SPEC-091: the user may link a conflict to any manual run that day that this import
    # does not link automatically.
    linked_runs = {int(cast(int, link["run_id"])) for link in links}
    for conflict in conflicts:
        conflict["candidate_run_ids"] = [
            manual[0] for manual in manual_by_date[str(conflict["date"])] if manual[0] not in linked_runs
        ]
    links.sort(key=lambda link: (str(link["date"]), str(link["strava_id"])))
    conflicts.sort(key=lambda conflict: (str(conflict["date"]), str(conflict["strava_id"])))
    return links, conflicts


class ConflictChoiceError(ValueError):
    """A conflict choice that does not match the current preview (SPEC-091)."""


class DuplicateConflictLinkError(ConflictChoiceError):
    """Two conflicts chose the same manual run; re-previewing cannot fix it (SPEC-092)."""


SKIP_CONFLICT = "skip"
IMPORT_CONFLICT = "import"


def resolve_conflicts(
    conflicts: list[dict[str, object]],
    choices: dict[str, object],
    manual_runs: Sequence[tuple[int, str, float, int | None]],
) -> tuple[list[dict[str, object]], set[str]]:
    """Apply the user's choice for each same-day conflict (SPEC-091).

    A choice is "skip" (the default for an activity without one), "import" (a new run) or
    the id of one of the conflict's candidate manual runs, which links like an automatic
    match: distance, date and shoe stay as entered. A missing moving time is filled only when
    the two distances are close and the pace is plausible; Strava's time for a different
    distance would give the typed run a wrong pace. Returns the extra links and the Strava IDs to import. A choice for an activity
    that is not a conflict, a run that is not a candidate, or one run chosen twice raises
    ConflictChoiceError, so a stale preview is never applied.
    """
    by_id = {str(conflict["strava_id"]): conflict for conflict in conflicts}
    manual_by_id = {manual[0]: manual for manual in manual_runs}
    links: list[dict[str, object]] = []
    imports: set[str] = set()
    chosen_runs: set[int] = set()
    for strava_id, choice in choices.items():
        conflict = by_id.get(str(strava_id))
        if conflict is None:
            raise ConflictChoiceError("not a conflict")
        if choice == SKIP_CONFLICT:
            continue
        if choice == IMPORT_CONFLICT:
            imports.add(str(strava_id))
            continue
        if isinstance(choice, bool) or not isinstance(choice, int):
            raise ConflictChoiceError("unknown choice")
        if choice not in cast(list[int], conflict["candidate_run_ids"]):
            raise ConflictChoiceError("not a candidate")
        if choice in chosen_runs:
            raise DuplicateConflictLinkError("run chosen twice")
        chosen_runs.add(choice)
        manual = manual_by_id[choice]
        duration = conflict.get("duration_seconds")
        fill = (
            duration
            if manual[3] is None and isinstance(duration, int) and is_plausible_duration(duration, manual[2])
            and _close_km(float(str(conflict["km"])), manual[2])
            else None
        )
        links.append({"strava_id": str(strava_id), "run_id": choice, "date": conflict["date"], "duration_seconds": fill})
    return links, imports
