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


class ShoeUpdate(ShoeBase):
    pass


class ShoeOut(ShoeBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
