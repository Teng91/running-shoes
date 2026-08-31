from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    shoes: Mapped[list["Shoe"]] = relationship(back_populates="owner")
    monthly_mileages: Mapped[list["MonthlyMileage"]] = relationship(back_populates="owner")
    runs: Mapped[list["Run"]] = relationship(back_populates="owner")


class Shoe(Base):
    __tablename__ = "shoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    brand: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)           # YYYY-MM-DD
    size: Mapped[str] = mapped_column(String, default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    orig_price: Mapped[float] = mapped_column(Float, default=0)
    mileage: Mapped[float] = mapped_column(Float, default=0)
    expected_mileage: Mapped[float] = mapped_column(Float, default=800)
    monthly_km: Mapped[float] = mapped_column(Float, default=60)
    is_retired: Mapped[bool] = mapped_column(Boolean, default=False)
    categories: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["Daily"], nullable=False)

    owner: Mapped["User"] = relationship(back_populates="shoes")


class MonthlyMileage(Base):
    __tablename__ = "monthly_mileages"
    __table_args__ = (UniqueConstraint("user_id", "year", "month", name="uq_user_year_month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    km: Mapped[float] = mapped_column(Float, default=0)

    owner: Mapped["User"] = relationship(back_populates="monthly_mileages")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("idx_runs_user_date", "user_id", "date"),
        Index(
            "idx_runs_user_strava_id",
            "user_id",
            "strava_id",
            unique=True,
            sqlite_where=text("strava_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    shoe_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shoes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD
    km: Mapped[float] = mapped_column(Float, nullable=False)
    strava_id: Mapped[str | None] = mapped_column(String, nullable=True)

    owner: Mapped["User"] = relationship(back_populates="runs")
    shoe: Mapped["Shoe"] = relationship()
