from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict


SHOE_CATEGORIES = Literal["Daily", "Speed", "Tempo", "Race"]


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
    category: SHOE_CATEGORIES = "Daily"


class ShoeCreate(ShoeBase):
    pass  # user_id is set by the backend, never by the client


class ShoeUpdate(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    date: Optional[str] = None
    size: Optional[str] = None
    price: Optional[float] = None
    orig_price: Optional[float] = None
    mileage: Optional[float] = None
    expected_mileage: Optional[float] = None
    monthly_km: Optional[float] = None
    is_retired: Optional[bool] = None
    category: Optional[SHOE_CATEGORIES] = None


class ShoeOut(ShoeBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int


# ── Monthly Mileage Schemas ───────────────────────────────────

class MonthlyMileageBase(BaseModel):
    year: int
    month: int
    km: float = 0


class MonthlyMileageCreate(MonthlyMileageBase):
    pass  # user_id is set by the backend, never by the client


class MonthlyMileageUpdate(BaseModel):
    year: Optional[int] = None
    month: Optional[int] = None
    km: Optional[float] = None


class MonthlyMileageOut(MonthlyMileageBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
