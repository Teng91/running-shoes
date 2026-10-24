"""Bounded, credential-free account archive contract (v1 and v2)."""

import json
import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend import schemas
from backend.services.errors import Invalid
from backend.services.run_requests import payload_hash

MAX_BACKUP_BYTES = 20 * 1024 * 1024
ARCHIVE_LIMITS = {"shoes": 5000, "runs": 50_000, "monthly_mileages": 2412,
                  "monthly_reports": 2412, "strava_imports": 1000, "history": 50_000}


class BackupShoe(schemas.ShoeCreate):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    baseline_mileage: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    is_deleted: bool = False


class BackupRun(schemas.RunCreate):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    strava_id: str | None = Field(default=None, max_length=128)


class BackupMonth(schemas.MonthlyMileageCreate):
    model_config = ConfigDict(extra="forbid")
    adjustment_km: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)


class BackupGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_year: schemas.ReasonableYear
    monthly_km: float = Field(gt=0, le=100_000, allow_inf_nan=False)
    yearly_km: float = Field(gt=0, le=1_200_000, allow_inf_nan=False)


class BackupReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: schemas.ReasonableYear
    month: schemas.CalendarMonth
    content_md: str = Field(max_length=100_000)
    model: str = Field(max_length=200)
    stats_json: dict
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BackupImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imported_at: datetime
    start_date: str = Field(max_length=10)
    end_date: str = Field(max_length=10)
    imported_count: int = Field(ge=0, le=50_000)
    imported_km: float = Field(ge=0, le=50_000_000, allow_inf_nan=False)
    duplicate_count: int = Field(ge=0, le=50_000)
    unmapped_count: int = Field(ge=0, le=50_000)
    invalid_count: int = Field(ge=0, le=50_000)


class BackupHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    operation_id: str = Field(max_length=128)
    reason: str = Field(max_length=40)
    entity: Literal["shoes", "runs", "monthly_mileages", "running_goals"]
    entity_id: int = Field(gt=0)
    action: Literal["insert", "update", "delete"]
    before_json: dict | None
    after_json: dict | None
    created_at: str = Field(max_length=40)
    restored: bool = False
    imported: bool = False


class AccountBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["running-shoes-account-backup"]
    version: Literal[1, 2]
    source_id: str | None = Field(default=None, min_length=16, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    exported_at: datetime
    username: str = Field(max_length=50)
    shoes: list[BackupShoe] = Field(max_length=ARCHIVE_LIMITS["shoes"])
    runs: list[BackupRun] = Field(max_length=ARCHIVE_LIMITS["runs"])
    monthly_mileages: list[BackupMonth] = Field(max_length=ARCHIVE_LIMITS["monthly_mileages"])
    running_goal: BackupGoal | None = None
    monthly_reports: list[BackupReport] = Field(default_factory=list, max_length=ARCHIVE_LIMITS["monthly_reports"])
    strava_imports: list[BackupImport] = Field(default_factory=list, max_length=ARCHIVE_LIMITS["strava_imports"])
    history: list[BackupHistory] = Field(default_factory=list, max_length=ARCHIVE_LIMITS["history"])

    @model_validator(mode="after")
    def validate_graph(self):
        if self.version == 2 and not self.source_id:
            raise ValueError("備份 v2 缺少 source_id")
        collections: list[tuple[list[Any], Any]] = [(self.shoes, lambda row: row.id), (self.runs, lambda row: row.id),
                            (self.monthly_mileages, lambda row: (row.year, row.month)),
                            (self.monthly_reports, lambda row: (row.year, row.month)),
                            (self.history, lambda row: row.id)]
        for items, keys in collections:
            values = [keys(row) for row in items]
            if len(values) != len(set(values)):
                raise ValueError("備份含有重複識別碼或月份")
        shoe_ids = {row.id for row in self.shoes}
        strava_ids = [row.strava_id for row in self.runs if row.strava_id]
        if len(strava_ids) != len(set(strava_ids)) or any(row.shoe_id not in shoe_ids for row in self.runs):
            raise ValueError("跑步鞋款參照或 Strava 識別碼不正確")
        by_shoe: dict[int, float] = {}
        by_month: dict[tuple[int, int], float] = {}
        for run in self.runs:
            by_shoe[run.shoe_id] = by_shoe.get(run.shoe_id, 0) + run.km
            period = (int(run.date[:4]), int(run.date[5:7]))
            by_month[period] = by_month.get(period, 0) + run.km
        for shoe in self.shoes:
            logged = round(by_shoe.get(shoe.id, 0), 2)
            baseline = shoe.mileage - logged if shoe.baseline_mileage is None else shoe.baseline_mileage
            if baseline < -0.005 or abs(baseline + logged - shoe.mileage) > 0.011:
                raise ValueError("鞋款總里程與歷史調整／日誌不一致")
            shoe.baseline_mileage = round(max(0, baseline), 2)
        for month in self.monthly_mileages:
            logged = round(by_month.get((month.year, month.month), 0), 2)
            adjustment = month.km - logged if month.adjustment_km is None else month.adjustment_km
            if adjustment < -0.005 or abs(adjustment + logged - month.km) > 0.011:
                raise ValueError("月跑量與歷史調整／日誌不一致")
            month.adjustment_km = round(max(0, adjustment), 2)
        return self


def parse_backup(raw: bytes) -> AccountBackup:
    if len(raw) > MAX_BACKUP_BYTES:
        raise Invalid("備份不可超過 20 MB")
    try:
        value = json.loads(raw)
        _check_json(value)
        return AccountBackup.model_validate(value)
    except (ValueError, TypeError, RecursionError, ValidationError) as exc:
        # Never echo arbitrary uploaded content or credentials in error messages.
        raise Invalid("備份格式、數值、日期或資料參照不正確") from exc


def _check_json(value, depth=0):
    if depth > 24:
        raise ValueError("nested backup")
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in {"password", "hashed_password", "secret_key", "api_key", "access_token", "token_version", "user_id"}:
                raise ValueError("credentials or user scope in backup")
            _check_json(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_json(child, depth + 1)
    elif isinstance(value, str) and len(value) > 100_000:
        raise ValueError("oversized string")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite number")


def backup_fingerprint(backup: AccountBackup) -> str:
    return payload_hash(backup.model_dump(mode="json"))


def validate_export(payload: dict) -> None:
    """Accept only archives the same import contract can consume, without truncation."""
    try:
        # Match JSONResponse's UTF-8 wire encoding, including compact separators.
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        parse_backup(raw)
    except (Invalid, ValueError, TypeError, RecursionError) as exc:
        raise Invalid("帳號資料超過 JSON 備份容量或不符合匯入格式，未產生下載檔。可取消包含異動歷史後再下載；若仍超限，請使用管理員完整資料庫備份。") from exc
