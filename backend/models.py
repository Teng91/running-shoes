from datetime import UTC, datetime
from uuid import uuid4

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

    backup_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), server_default="", nullable=False)
    # Verified recovery address (SPEC-079); only set after the emailed code is confirmed.
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    data_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    shoes: Mapped[list["Shoe"]] = relationship(back_populates="owner")
    monthly_mileages: Mapped[list["MonthlyMileage"]] = relationship(back_populates="owner")
    running_goal: Mapped["RunningGoal | None"] = relationship(back_populates="owner")
    runs: Mapped[list["Run"]] = relationship(back_populates="owner")
    strava_imports: Mapped[list["StravaImport"]] = relationship(back_populates="owner")


class RateLimitBucket(Base):
    """Shared fixed-window counters used across server processes."""

    __tablename__ = "rate_limit_buckets"
    __table_args__ = (UniqueConstraint("scope", "bucket_key", name="uq_rate_limit_bucket"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    bucket_key: Mapped[str] = mapped_column(String(128), nullable=False)
    window_started: Mapped[float] = mapped_column(Float, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Shoe(Base):
    __tablename__ = "shoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nickname: Mapped[str] = mapped_column(String(80), default="", server_default="", nullable=False)
    brand: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)           # YYYY-MM-DD
    size: Mapped[str] = mapped_column(String, default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    orig_price: Mapped[float] = mapped_column(Float, default=0)
    mileage: Mapped[float] = mapped_column(Float, default=0)
    # Portion of total mileage that predates (or was manually adjusted outside)
    # the run log.  Keeping it explicit makes mileage provenance auditable while
    # preserving imported historical totals.
    baseline_mileage: Mapped[float] = mapped_column(Float, default=0, nullable=False)
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
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    km: Mapped[float] = mapped_column(Float, default=0)
    # Historical/manual contribution.  ``km`` remains the materialized total
    # for backwards compatibility: adjustment_km + the matching run log sum.
    adjustment_km: Mapped[float] = mapped_column(Float, default=0, nullable=False)

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


class ReportGeneration(Base):
    """Latest started generation; never exposed as a saved report."""

    __tablename__ = "report_generations"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(36), nullable=False)


class RunningGoal(Base):
    __tablename__ = "running_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_year: Mapped[int] = mapped_column(Integer, default=2026, nullable=False)
    monthly_km: Mapped[float] = mapped_column(Float, default=125, nullable=False)
    yearly_km: Mapped[float] = mapped_column(Float, default=1500, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="running_goal")


class EmailCode(Base):
    """One pending email code per account and purpose (SPEC-079); only an HMAC is stored."""

    __tablename__ = "email_codes"
    __table_args__ = (UniqueConstraint("user_id", "purpose", name="uq_email_codes_user_purpose"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Invite(Base):
    """Registration invite (SPEC-075); only a SHA-256 of the code is stored.

    Invites belong to the site, not to an account, so deleting the admin's account
    never blocks on or removes them.
    """

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    note: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class RaceGoal(Base):
    """One target race per user with an optional reference result (SPEC-065)."""

    __tablename__ = "race_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    race_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    race_date: Mapped[str] = mapped_column(String(10), nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    target_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)


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
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shoe_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shoes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD
    km: Mapped[float] = mapped_column(Float, nullable=False)
    strava_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Moving time in whole seconds (SPEC-060); pace is derived in backend.run_metrics.
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

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


class MutationReceipt(Base):
    """The single replay receipt for keyed mutations, including run creation."""

    __tablename__ = "mutation_receipts"
    __table_args__ = (Index("idx_receipts_user_recorded", "user_id", "recorded_at"),)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Epoch seconds; retention keeps each account's newest receipts.
    recorded_at: Mapped[float] = mapped_column(
        Float, default=lambda: datetime.now(UTC).timestamp(), server_default="0", nullable=False
    )


class RunTombstone(Base):
    """A locally deleted run, so neither a backup nor a Strava re-import resurrects it."""

    __tablename__ = "run_tombstones"
    __table_args__ = (
        Index(
            "idx_run_tombstones_user_strava",
            "user_id",
            "strava_id",
            sqlite_where=text("strava_id IS NOT NULL"),
        ),
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Strava activity of the deleted run (schema 8); NULL for manual runs.
    strava_id: Mapped[str | None] = mapped_column(String, nullable=True)


class EntitySequence(Base):
    """Global primary-key allocator metadata; contains no account records."""
    __tablename__ = "entity_sequences"
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    next_id: Mapped[int] = mapped_column(Integer, nullable=False)


class WriteContext(Base):
    __tablename__ = "write_contexts"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("idx_audit_user_id", "user_id", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    entity: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    restored: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    imported: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)


class RestorePreview(Base):
    __tablename__ = "restore_previews"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    token: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RestoreMapping(Base):
    __tablename__ = "restore_mappings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(90), primary_key=True)
    entity: Mapped[str] = mapped_column(String(30), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
