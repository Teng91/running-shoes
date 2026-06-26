from sqlalchemy import Column, Integer, String, Float, Boolean
from backend.database import Base


class Shoe(Base):
    __tablename__ = "shoes"

    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String, nullable=False)
    model = Column(String, nullable=False)
    date = Column(String, nullable=False)           # YYYY-MM-DD
    size = Column(String, default="")
    price = Column(Float, default=0)
    orig_price = Column(Float, default=0)
    mileage = Column(Float, default=0)
    expected_mileage = Column(Float, default=800)
    monthly_km = Column(Float, default=60)
    is_retired = Column(Boolean, default=False)
