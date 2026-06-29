from typing import Optional
from pydantic import BaseModel, ConfigDict


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
    pass


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
