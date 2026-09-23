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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    shoes: Mapped[list["Shoe"]] = relationship(back_populates="owner")
    monthly_mileages: Mapped[list["MonthlyMileage"]] = relationship(back_populates="owner")
    running_goal: Mapped["RunningGoal | None"] = relationship(back_populates="owner")
    runs: Mapped[list["Run"]] = relationship(back_populates="owner")
    strava_imports: Mapped[list["StravaImport"]] = relationship(back_populates="owner")


class Shoe(Base):
    __tablename__ = "shoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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


class MonthlyReport(Base):
    __tablename__ = "monthly_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "year", "month", name="uq_user_year_month_report"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model: Mapped[str] = mapped_column(String, default="", nullable=False)
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class RunningGoal(Base):
    __tablename__ = "running_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )
    start_year: Mapped[int] = mapped_column(Integer, default=2026, nullable=False)
    monthly_km: Mapped[float] = mapped_column(Float, default=125, nullable=False)
    yearly_km: Mapped[float] = mapped_column(Float, default=1500, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="running_goal")


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


class StravaImport(Base):
    __tablename__ = "strava_imports"
    __table_args__ = (Index("idx_strava_imports_user_time", "user_id", "imported_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    start_date: Mapped[str] = mapped_column(String, default="", nullable=False)
    end_date: Mapped[str] = mapped_column(String, default="", nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_km: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unmapped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="strava_imports")
