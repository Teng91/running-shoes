import math
from datetime import UTC, datetime
from datetime import date as calendar_date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

# All valid shoe purpose/function categories.
SHOE_CATEGORIES = ["Daily", "Speed", "Tempo", "Race"]
ReasonableYear = Annotated[int, Field(ge=1900, le=2100)]
CalendarMonth = Annotated[int, Field(ge=1, le=12)]
NonNegativeFiniteKm = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveFiniteKm = Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]
MAX_PASSWORD_BYTES = 72
Username = Annotated[str, Field(min_length=1, max_length=50)]
ShoeName = Annotated[str, Field(min_length=1, max_length=100)]
ShoeSize = Annotated[str, Field(max_length=50)]


def _validate_password(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} UTF-8 bytes")
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


# ── Auth Schemas ──────────────────────────────────────────────

class UserCreate(BaseModel):
    username: Username
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class UserLogin(BaseModel):
    username: Username
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str


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


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: ReasonableYear
    month: CalendarMonth
    model: str | None = Field(default=None, min_length=1, max_length=200)


class UserChangePassword(BaseModel):
    username: Username
    old_password: str
    new_password: str

    @field_validator("old_password", "new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password(value)


# ── Shoe Schemas ──────────────────────────────────────────────

class ShoeBase(BaseModel):
    brand: ShoeName
    model: ShoeName
    date: str
    size: ShoeSize = ""
    price: float = 0
    orig_price: float = 0
    mileage: float = 0
    expected_mileage: float = 800
    monthly_km: float = 60
    is_retired: bool = False
    categories: list[str] = Field(default_factory=lambda: ["Daily"], max_length=len(SHOE_CATEGORIES))

    @field_validator("brand", "model")
    @classmethod
    def validate_names(cls, value: str) -> str:
        return _validate_non_blank(value)

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, v):
        if len(v) != len(set(v)):
            raise ValueError("categories must not contain duplicates")
        invalid = [c for c in v if c not in SHOE_CATEGORIES]
        if invalid:
            raise ValueError(
                f"Invalid categories: {invalid}. Must be subset of {SHOE_CATEGORIES}"
            )
        return v

    @field_validator("price", "orig_price", "mileage", "expected_mileage", "monthly_km")
    @classmethod
    def validate_non_negative(cls, v):
        if v is None:
            return v
        # Reject NaN/Inf — SQLite treats them as NULL and the NOT NULL
        # constraint turns a legit client into a 500.
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("must be a finite number")
        if v < 0:
            raise ValueError("must be non-negative")
        return v


class ShoeCreate(ShoeBase):
    # user_id is set by the backend, never by the client.
    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_iso_date(value)


class ShoeUpdate(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)
    brand: ShoeName | None = None
    model: ShoeName | None = None
    date: str | None = None
    size: ShoeSize | None = None
    price: float | None = None
    orig_price: float | None = None
    mileage: float | None = None
    expected_mileage: float | None = None
    monthly_km: float | None = None
    is_retired: bool | None = None
    categories: Annotated[list[str], Field(max_length=len(SHOE_CATEGORIES))] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value):
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("shoe fields may be omitted but must not be null")
        return value

    @field_validator("brand", "model")
    @classmethod
    def validate_names(cls, value: str | None) -> str | None:
        return _validate_non_blank(value) if value is not None else None

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value) if value is not None else None

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, v):
        if v is not None:
            if len(v) != len(set(v)):
                raise ValueError("categories must not contain duplicates")
            invalid = [c for c in v if c not in SHOE_CATEGORIES]
            if invalid:
                raise ValueError(
                    f"Invalid categories: {invalid}. Must be subset of {SHOE_CATEGORIES}"
                )
        return v

    @field_validator("price", "orig_price", "mileage", "expected_mileage", "monthly_km")
    @classmethod
    def validate_non_negative(cls, v):
        if v is None:
            return v
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("must be a finite number")
        if v < 0:
            raise ValueError("must be non-negative")
        return v


class ShoeOut(ShoeBase):
    version: int = 0
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int


# ── Monthly Mileage Schemas ───────────────────────────────────

class MonthlyMileageBase(BaseModel):
    year: ReasonableYear
    month: CalendarMonth
    km: NonNegativeFiniteKm = 0


class MonthlyMileageCreate(MonthlyMileageBase):
    pass  # user_id is set by the backend, never by the client


class MonthlyMileageUpdate(BaseModel):
    year: ReasonableYear | None = None
    month: CalendarMonth | None = None
    km: NonNegativeFiniteKm | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value):
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("monthly mileage fields may be omitted but must not be null")
        return value


class MonthlyMileageOut(MonthlyMileageBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int


class RunningGoalUpdate(BaseModel):
    start_year: ReasonableYear
    monthly_km: Annotated[float, Field(gt=0, le=100_000, allow_inf_nan=False)]


class RunningGoalOut(RunningGoalUpdate):
    yearly_km: float


# ── Run Log Schemas ────────────────────────────────────

class RunBase(BaseModel):
    date: str
    km: PositiveFiniteKm
    shoe_id: int = Field(gt=0)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_iso_date(value)


class RunCreate(RunBase):
    pass


class RunUpdate(BaseModel):
    date: str | None = None
    km: PositiveFiniteKm | None = None
    shoe_id: int | None = Field(default=None, gt=0)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("date must not be null")
        return _validate_iso_date(value)

    @field_validator("km")
    @classmethod
    def validate_km(cls, value: float | None) -> float:
        if value is None:
            raise ValueError("km must not be null")
        return value

    @field_validator("shoe_id")
    @classmethod
    def validate_shoe_id(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("shoe_id must not be null")
        return value


class RunOut(RunBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    strava_id: str | None = None


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
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
