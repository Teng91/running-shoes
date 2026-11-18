import math
from datetime import UTC, datetime
from datetime import date as calendar_date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

from backend.clock import local_today
from backend.run_metrics import MAX_RUN_DURATION_SECONDS, is_plausible_duration, pace_seconds_per_km

# All valid shoe purpose/function categories.
SHOE_CATEGORIES = ["Daily", "Speed", "Tempo", "Race"]
TWO_DECIMALS = Decimal("0.01")
MAX_SHOE_PRICE = 100_000_000.0
MAX_SHOE_MILEAGE_KM = 1_000_000.0
MAX_SHOE_MONTHLY_KM = 100_000.0
MAX_MONTHLY_MILEAGE_KM = 1_000_000.0
ReasonableYear = Annotated[int, Field(ge=1900, le=2100)]
CalendarMonth = Annotated[int, Field(ge=1, le=12)]
NonNegativeFiniteKm = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveFiniteKm = Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]
RunDurationSeconds = Annotated[int, Field(ge=1, le=MAX_RUN_DURATION_SECONDS, strict=True)]
MAX_PASSWORD_BYTES = 72
MAX_AGENT_CONTEXT_CHARS = 60_000
Username = Annotated[str, Field(min_length=1, max_length=50)]
ShoeName = Annotated[str, Field(min_length=1, max_length=100)]
ShoeSize = Annotated[str, Field(max_length=50)]


def serialize_utc_timestamp(value: datetime) -> str:
    """SQLite drops timezone metadata; application timestamps are stored as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _validate_password(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} UTF-8 bytes")
    return value


Password = Annotated[str, AfterValidator(_validate_password)]


def _reject_explicit_nulls(value, label: str):
    """Partial updates may omit fields, but an explicit null is a client error."""
    if isinstance(value, dict) and any(item is None for item in value.values()):
        raise ValueError(f"{label} fields may be omitted but must not be null")
    return value


def _validate_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _validate_iso_date(value: str) -> str:
    try:
        parsed = calendar_date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("date must be a valid YYYY-MM-DD calendar date") from None
    if not 1900 <= parsed.year <= 2100:
        raise ValueError("year must be between 1900 and 2100")
    if parsed.isoformat() != value:
        raise ValueError("date must use YYYY-MM-DD format")
    return value


def _validate_completed_run_date(value: str) -> str:
    value = _validate_iso_date(value)
    today = local_today()
    if calendar_date.fromisoformat(value) > today:
        raise ValueError("run date must not be in the future")
    return value


def _round_two_decimals(value: float) -> float:
    """Store user-entered money and distance with one canonical precision."""
    try:
        return float(Decimal(str(value)).quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("must be a finite number") from None


# ── Auth Schemas ──────────────────────────────────────────────

class UserCreate(BaseModel):
    username: Username
    password: Password
    # Required while registration is invite-only (SPEC-075).
    invite_code: str = Field("", max_length=20)


class UserLogin(BaseModel):
    username: Username
    password: Password


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    is_admin: bool = False


class RegistrationOut(BaseModel):
    mode: Literal["invite", "open", "closed"]


class AccountDelete(BaseModel):
    password: Password


class InviteCreate(BaseModel):
    note: str = Field("", max_length=60)
    max_uses: int = Field(1, ge=1, le=20)
    days: int = Field(14, ge=1, le=90)


class AdminPasswordReset(BaseModel):
    username: Username


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Agent Schemas ────────────────────────────────────────────

class AgentHistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_message: str = Field(min_length=1, max_length=12_000)
    history: list[AgentHistoryTurn] = Field(default_factory=list, max_length=20)
    provider: Literal["openrouter"] = "openrouter"
    model: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("user_message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_message cannot be blank")
        return value

    @model_validator(mode="after")
    def limit_total_context(self):
        total_chars = len(self.user_message) + sum(
            len(turn.content) for turn in self.history
        )
        if total_chars > MAX_AGENT_CONTEXT_CHARS:
            raise ValueError(
                f"agent conversation context must be at most "
                f"{MAX_AGENT_CONTEXT_CHARS} characters"
            )
        return self


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: ReasonableYear
    month: CalendarMonth
    model: str | None = Field(default=None, min_length=1, max_length=200)


class UserChangePassword(BaseModel):
    username: Username
    old_password: Password
    new_password: Password


# ── Shoe Schemas ──────────────────────────────────────────────

def _finite_non_negative(value: float) -> float:
    # Reject NaN/Inf — SQLite treats them as NULL and the NOT NULL
    # constraint turns a legit client into a 500.
    if not math.isfinite(value):
        raise ValueError("must be a finite number")
    if value < 0:
        raise ValueError("must be non-negative")
    return _round_two_decimals(value)


def _at_most(limit: float) -> AfterValidator:
    def check(value: float) -> float:
        if value > limit:
            raise ValueError(f"must be at most {limit:g}")
        return value
    return AfterValidator(check)


def _shoe_categories(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError("categories must not contain duplicates")
    invalid = [category for category in values if category not in SHOE_CATEGORIES]
    if invalid:
        raise ValueError(f"Invalid categories: {invalid}. Must be subset of {SHOE_CATEGORIES}")
    return values


# One definition per field rule, shared by create, update and output schemas.
NonBlankShoeName = Annotated[ShoeName, AfterValidator(_validate_non_blank)]
ShoeAmount = Annotated[float, AfterValidator(_finite_non_negative)]
ShoePrice = Annotated[ShoeAmount, _at_most(MAX_SHOE_PRICE)]
ShoeMileage = Annotated[ShoeAmount, _at_most(MAX_SHOE_MILEAGE_KM)]
ShoeMonthlyKm = Annotated[ShoeAmount, _at_most(MAX_SHOE_MONTHLY_KM)]
ShoeCategories = Annotated[
    list[str], Field(max_length=len(SHOE_CATEGORIES)), AfterValidator(_shoe_categories)
]
ShoePurchaseDate = Annotated[str, AfterValidator(_validate_iso_date)]


class ShoeBase(BaseModel):
    nickname: str = Field(default="", max_length=80)
    brand: NonBlankShoeName
    model: NonBlankShoeName
    date: str
    size: ShoeSize = ""
    price: ShoeAmount = 0
    orig_price: ShoeAmount = 0
    mileage: ShoeAmount = 0
    expected_mileage: ShoeAmount = 800
    monthly_km: ShoeAmount = 60
    is_retired: bool = False
    categories: ShoeCategories = Field(default_factory=lambda: ["Daily"])


class ShoeCreate(ShoeBase):
    # user_id is set by the backend, never by the client.
    date: ShoePurchaseDate
    price: ShoePrice = 0
    orig_price: ShoePrice = 0
    mileage: ShoeMileage = 0
    expected_mileage: ShoeMileage = 800
    monthly_km: ShoeMonthlyKm = 60


class ShoeUpdate(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    nickname: str | None = Field(default=None, max_length=80)
    brand: NonBlankShoeName | None = None
    model: NonBlankShoeName | None = None
    date: ShoePurchaseDate | None = None
    size: ShoeSize | None = None
    price: ShoePrice | None = None
    orig_price: ShoePrice | None = None
    mileage: ShoeMileage | None = None
    expected_mileage: ShoeMileage | None = None
    monthly_km: ShoeMonthlyKm | None = None
    is_retired: bool | None = None
    categories: ShoeCategories | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value):
        return _reject_explicit_nulls(value, "shoe")


class ShoeOut(ShoeBase):
    discount_percent: float | None = None
    cost_per_km: float | None = None
    expected_cost_per_km: float | None = None
    usage_percent: float | None = None
    remaining_mileage_km: float = 0
    forecast_retirement_date: str | None = None
    forecast_source: Literal["recent_90_days", "planned_monthly_km", "idle_90_days", "retired"] | None = None
    forecast_monthly_km: float = 0
    actual_monthly_km_90_days: float = 0
    version: int = 0
    baseline_mileage: float = 0
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int


# ── Monthly Mileage Schemas ───────────────────────────────────

class MonthlyMileageBase(BaseModel):
    year: ReasonableYear
    month: CalendarMonth
    km: NonNegativeFiniteKm = 0

    @field_validator("km")
    @classmethod
    def normalize_km(cls, value: float) -> float:
        return _round_two_decimals(value)


class MonthlyMileageCreate(MonthlyMileageBase):
    @field_validator("km")
    @classmethod
    def validate_km_limit(cls, value: float) -> float:
        if value > MAX_MONTHLY_MILEAGE_KM:
            raise ValueError(f"must be at most {MAX_MONTHLY_MILEAGE_KM:g}")
        return value


class MonthlyMileageUpdate(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    year: ReasonableYear | None = None
    month: CalendarMonth | None = None
    km: NonNegativeFiniteKm | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value):
        return _reject_explicit_nulls(value, "monthly mileage")

    @field_validator("km")
    @classmethod
    def normalize_km(cls, value: float | None) -> float | None:
        if value is None:
            return value
        value = _round_two_decimals(value)
        if value > MAX_MONTHLY_MILEAGE_KM:
            raise ValueError(f"must be at most {MAX_MONTHLY_MILEAGE_KM:g}")
        return value


class MonthlyMileageOut(MonthlyMileageBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    version: int = 0
    adjustment_km: float = 0


class RunningGoalUpdate(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    start_year: ReasonableYear
    monthly_km: Annotated[float, Field(gt=0, le=100_000, allow_inf_nan=False)]

    @field_validator("monthly_km")
    @classmethod
    def normalize_monthly_km(cls, value: float) -> float:
        value = _round_two_decimals(value)
        if value < 0.01:
            raise ValueError("monthly_km must be at least 0.01")
        return value


class RunningGoalOut(RunningGoalUpdate):
    expected_version: int | None = Field(default=None, exclude=True)
    version: int = 0
    yearly_km: float


# ── Race Goal Schemas (SPEC-065) ─────────────────────────

RaceDistanceKm = Annotated[float, Field(ge=1, le=250, allow_inf_nan=False)]
RaceSeconds = Annotated[int, Field(ge=60, le=MAX_RUN_DURATION_SECONDS, strict=True)]


class RaceGoalUpdate(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    race_name: Annotated[str, Field(max_length=80)] = ""
    race_date: str
    distance_km: RaceDistanceKm
    target_seconds: RaceSeconds
    reference_distance_km: RaceDistanceKm | None = None
    reference_seconds: RaceSeconds | None = None
    reference_temperature_c: Annotated[float, Field(ge=-30, le=50, allow_inf_nan=False)] | None = None

    @field_validator("race_name")
    @classmethod
    def strip_race_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("race_date")
    @classmethod
    def validate_race_date(cls, value: str) -> str:
        try:
            parsed = calendar_date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("race_date must be YYYY-MM-DD") from exc
        if not 1900 <= parsed.year <= 2100 or parsed.isoformat() != value:
            raise ValueError("race_date must be YYYY-MM-DD")
        return value

    @field_validator("distance_km", "reference_distance_km")
    @classmethod
    def round_distance(cls, value: float | None) -> float | None:
        return None if value is None else round(value, 4)

    @model_validator(mode="after")
    def validate_paces(self) -> "RaceGoalUpdate":
        if not is_plausible_duration(self.target_seconds, self.distance_km):
            raise ValueError("target_seconds must give a pace between 1:00 and 60:00 per km")
        if (self.reference_distance_km is None) != (self.reference_seconds is None):
            raise ValueError("reference_distance_km and reference_seconds go together")
        if self.reference_seconds is None and self.reference_temperature_c is not None:
            raise ValueError("reference_temperature_c needs a reference result")
        if (self.reference_seconds is not None and self.reference_distance_km is not None
                and not is_plausible_duration(self.reference_seconds, self.reference_distance_km)):
            raise ValueError("reference_seconds must give a pace between 1:00 and 60:00 per km")
        return self


class RaceGoalOut(BaseModel):
    version: int
    race_name: str
    race_date: str
    distance_km: float
    target_seconds: int
    reference_distance_km: float | None
    reference_seconds: int | None
    reference_temperature_c: float | None


# ── Run Log Schemas ────────────────────────────────────

def _validate_run_pace(duration_seconds: int | None, km: float | None) -> None:
    if duration_seconds is not None and km is not None and not is_plausible_duration(duration_seconds, km):
        raise ValueError("duration_seconds must give a pace between 1:00 and 60:00 per km")


class RunBase(BaseModel):
    date: str
    km: PositiveFiniteKm
    shoe_id: int = Field(gt=0)
    # Optional moving time (SPEC-060); pace is derived, never accepted from clients.
    duration_seconds: RunDurationSeconds | None = None

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_iso_date(value)

    @field_validator("km")
    @classmethod
    def normalize_km(cls, value: float) -> float:
        value = _round_two_decimals(value)
        if value < 0.01:
            raise ValueError("km must be at least 0.01")
        return value

    @model_validator(mode="after")
    def validate_pace(self):
        _validate_run_pace(self.duration_seconds, self.km)
        return self


class RunCreate(RunBase):
    @field_validator("date")
    @classmethod
    def validate_completed_date(cls, value: str) -> str:
        return _validate_completed_run_date(value)


class RunUpdate(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    date: str | None = None
    km: PositiveFiniteKm | None = None
    shoe_id: int | None = Field(default=None, gt=0)
    # Unlike the other fields, an explicit null clears the stored moving time.
    duration_seconds: RunDurationSeconds | None = None

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("date must not be null")
        return _validate_completed_run_date(value)

    @field_validator("km")
    @classmethod
    def validate_km(cls, value: float | None) -> float:
        if value is None:
            raise ValueError("km must not be null")
        value = _round_two_decimals(value)
        if value < 0.01:
            raise ValueError("km must be at least 0.01")
        return value

    @field_validator("shoe_id")
    @classmethod
    def validate_shoe_id(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("shoe_id must not be null")
        return value

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value):
        # A null version used to reach SQL as `version IS NULL` and always
        # failed as a misleading 409; reject it like shoe and month updates.
        # duration_seconds is the exception: null clears the moving time.
        if isinstance(value, dict) and "duration_seconds" in value:
            _reject_explicit_nulls({k: v for k, v in value.items() if k != "duration_seconds"}, "run")
            return value
        return _reject_explicit_nulls(value, "run")

    @model_validator(mode="after")
    def validate_pace(self):
        _validate_run_pace(self.duration_seconds, self.km)
        return self


class RunOut(RunBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    version: int = 0
    strava_id: str | None = None
    # Stored rows are trusted: a moving time kept across a distance edit still serializes.
    duration_seconds: int | None = None

    @model_validator(mode="after")
    def validate_pace(self):
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pace_seconds_per_km(self) -> int | None:
        return pace_seconds_per_km(self.duration_seconds, self.km)


class StravaImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    imported_at: datetime
    start_date: str
    end_date: str
    imported_count: int
    imported_km: NonNegativeFiniteKm
    duplicate_count: int
    unmapped_count: int
    invalid_count: int

    @field_serializer("imported_at")
    def serialize_imported_at(self, value: datetime) -> str:
        return serialize_utc_timestamp(value)


class MutationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    kind: Literal["run.create", "run.update", "run.delete", "shoe.create", "shoe.update", "shoe.delete",
                  "monthly.create", "monthly.update", "monthly.delete", "goal.update", "history.restore"]
    entity_id: int | None = Field(default=None, gt=0)
    expected_version: int | None = Field(default=None, ge=0)
    payload: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_identity_and_version(self):
        if self.kind.endswith((".update", ".delete")) and self.expected_version is None:
            raise ValueError("更新與刪除必須提供 expected_version")
        if self.kind not in {"run.create", "shoe.create", "monthly.create", "goal.update"} and self.entity_id is None:
            raise ValueError("此操作必須提供 entity_id")
        return self
