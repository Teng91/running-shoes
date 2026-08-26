import math
from datetime import date as calendar_date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# All valid shoe purpose/function categories.
SHOE_CATEGORIES = ["Daily", "Speed", "Tempo", "Race", "Trail", "Walk"]
ReasonableYear = Annotated[int, Field(ge=1900, le=2100)]
CalendarMonth = Annotated[int, Field(ge=1, le=12)]
NonNegativeFiniteKm = Annotated[float, Field(ge=0, allow_inf_nan=False)]


def _validate_iso_date(value: str) -> str:
    try:
        parsed = calendar_date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("date must be a valid YYYY-MM-DD calendar date") from None
    if parsed.isoformat() != value:
        raise ValueError("date must use YYYY-MM-DD format")
    return value


# ── Auth Schemas ──────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


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


class UserChangePassword(BaseModel):
    username: str
    old_password: str
    new_password: str


# ── Shoe Schemas ──────────────────────────────────────────────

class ShoeBase(BaseModel):
    brand: str
    model: str
    date: str
    size: str = ""
    price: float = 0
    orig_price: float = 0
    mileage: float = 0
    expected_mileage: float = 800
    monthly_km: float = 60
    is_retired: bool = False
    categories: list[str] = ["Daily"]

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, v):
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
    brand: str | None = None
    model: str | None = None
    date: str | None = None
    size: str | None = None
    price: float | None = None
    orig_price: float | None = None
    mileage: float | None = None
    expected_mileage: float | None = None
    monthly_km: float | None = None
    is_retired: bool | None = None
    categories: list[str] | None = None

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value) if value is not None else None

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, v):
        if v is not None:
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


class MonthlyMileageOut(MonthlyMileageBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
