from typing import Optional
from pydantic import BaseModel, ConfigDict


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


class UserResetPassword(BaseModel):
    username: str
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


class ShoeOut(ShoeBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
