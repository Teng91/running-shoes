"""Ordered, idempotent SQLite schema migrations."""

from collections.abc import Callable
from typing import cast

from sqlalchemy import Table, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend import models
from backend.credentials import get_password_hash
from backend.database import Base

CURRENT_SCHEMA_VERSION = 4


def schema_version(engine: Engine) -> int:
    """Return the applied schema version, or zero for a legacy database."""
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        if "schema_metadata" not in tables:
            return 0
        value = connection.execute(
            text("SELECT value FROM schema_metadata WHERE key = 'schema_version'")
        ).scalar_one_or_none()
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def run_startup_migrations(
    engine: Engine,
    session_factory: Callable[[], Session],
    *,
    migration_password: str | None = None,
) -> None:
    applied_version = schema_version(engine)
    if applied_version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema {applied_version} is newer than supported "
            f"version {CURRENT_SCHEMA_VERSION}; refusing to downgrade"
        )

    # One-time migration: if old schema exists (shoes table without user_id), migrate
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    existing_shoe_columns = (
        {column["name"] for column in inspector.get_columns("shoes")}
        if "shoes" in existing_tables
        else set()
    )

    if "shoes" in existing_tables and "user_id" not in existing_shoe_columns:
        if not migration_password:
            raise RuntimeError(
                "MIGRATION_PASSWORD is required to migrate the legacy shoes database; "
                "refusing to start with an unusable schema."
            )

        # Old schema: create users table, add user_id to shoes, assign to "Joy"
        user_table = cast(Table, models.User.__table__)
        Base.metadata.create_all(bind=engine, tables=[user_table])
        with engine.begin() as conn:
            if "token_version" not in {c["name"] for c in inspect(conn).get_columns("users")}:
                conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
        db = session_factory()
        try:
            joy_user = db.query(models.User).filter(models.User.username == "Joy").first()
            if joy_user is None:
                joy_user = models.User(
                    username="Joy",
                    hashed_password=get_password_hash(migration_password),
                )
                db.add(joy_user)
                db.commit()
                db.refresh(joy_user)

            # Add user_id column (SQLite allows ALTER TABLE ADD COLUMN without FK)
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE shoes ADD COLUMN user_id INTEGER"))
                conn.execute(
                    text("UPDATE shoes SET user_id = :uid"),
                    {"uid": joy_user.id},
                )
                conn.commit()
        finally:
            db.close()

    Base.metadata.create_all(bind=engine, tables=[
        table for table in Base.metadata.sorted_tables if table.name not in {"run_creation_requests", "report_generations"}
    ])

    # Add concurrency/session versions to existing databases without changing data.
    for table, column in (
        ("users", "token_version"),
        ("shoes", "version"),
        ("shoes", "is_deleted"),
        ("runs", "version"),
        ("monthly_mileages", "version"),
        ("running_goals", "version"),
    ):
        columns = {item["name"] for item in inspect(engine).get_columns(table)}
        if column not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"))

    # Make historical/manual mileage explicit while preserving the exact totals
    # shown before this migration.  These baselines remain unchanged as runs are
    # added, edited, or deleted.
    shoe_columns = {column["name"] for column in inspect(engine).get_columns("shoes")}
    if "baseline_mileage" not in shoe_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE shoes ADD COLUMN baseline_mileage FLOAT NOT NULL DEFAULT 0"
            ))
            # Extremely old test/legacy tables may not yet have a mileage
            # column; their new baseline safely remains zero.
            if "mileage" in shoe_columns:
                conn.execute(text(
                    "UPDATE shoes SET baseline_mileage = mileage - COALESCE(("
                    "SELECT SUM(runs.km) FROM runs WHERE runs.shoe_id = shoes.id "
                    "AND runs.user_id = shoes.user_id), 0)"
                ))

    monthly_columns = {
        column["name"] for column in inspect(engine).get_columns("monthly_mileages")
    }
    if "adjustment_km" not in monthly_columns:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE monthly_mileages "
                "ADD COLUMN adjustment_km FLOAT NOT NULL DEFAULT 0"
            ))
            conn.execute(text(
                "UPDATE monthly_mileages SET adjustment_km = km - COALESCE(("
                "SELECT SUM(runs.km) FROM runs WHERE runs.user_id = monthly_mileages.user_id "
                "AND CAST(substr(runs.date, 1, 4) AS INTEGER) = monthly_mileages.year "
                "AND CAST(substr(runs.date, 6, 2) AS INTEGER) = monthly_mileages.month), 0)"
            ))

    # Incremental migration for Strava provenance on run records.
    run_columns = {column["name"] for column in inspect(engine).get_columns("runs")}
    with engine.begin() as conn:
        if "strava_id" not in run_columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN strava_id VARCHAR"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_user_strava_id "
            "ON runs (user_id, strava_id) WHERE strava_id IS NOT NULL"
        ))

    # create_all() does not add indexes to tables that already exist.
    # Keep the run-log query path fast for upgraded databases as history grows.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_runs_user_date "
            "ON runs (user_id, date)"
        ))
        conn.execute(text("PRAGMA optimize"))

    # Incremental migration for SQLite databases created before shoe categories
    # were changed from a single string to a JSON array of multiple purposes.
    # create_all() does not alter existing tables, so we need ALTER TABLE here.
    shoe_columns = {column["name"] for column in inspect(engine).get_columns("shoes")}
    with engine.begin() as conn:
        if "categories" not in shoe_columns:
            if "category" in shoe_columns:
                # Legacy DB: migrate single-string category → JSON array, then drop old column
                conn.execute(text("ALTER TABLE shoes ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'"))
                conn.execute(text("UPDATE shoes SET categories = json_array(category) WHERE category IS NOT NULL AND category != ''"))
                conn.execute(text("ALTER TABLE shoes DROP COLUMN category"))
            else:
                # Table exists but has no category column at all — add the new one
                conn.execute(text("ALTER TABLE shoes ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'"))
        # Remove discontinued categories in one pass, including repeated values.
        # Preserve the remaining labels and leave shoes with no remaining purpose unclassified.
        conn.execute(text("""
            UPDATE shoes
            SET categories = (
                SELECT json_group_array(value) FROM json_each(shoes.categories)
                WHERE value NOT IN ('Other', 'Walk', 'Trail')
            ), version = version + 1
            WHERE EXISTS (
                SELECT 1 FROM json_each(shoes.categories)
                WHERE value IN ('Other', 'Walk', 'Trail')
            )
        """))

    # Schema 2 is additive: receipts share the run transaction, with no changes
    # to existing run/shoe/monthly tables or mileage values.
    if applied_version < 2:
        cast(Table, models.RunCreationRequest.__table__).create(bind=engine, checkfirst=True)

    # Schema 3 adds display-only nicknames without rewriting mileage or versions.
    if applied_version < 3 and "nickname" not in {
        column["name"] for column in inspect(engine).get_columns("shoes")
    }:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE shoes ADD COLUMN nickname VARCHAR(80) NOT NULL DEFAULT ''"
            ))

    # Schema 4 adds one latest-generation receipt per user/month. Saved reports
    # remain untouched, and no empty placeholder report becomes visible.
    if applied_version < 4:
        cast(Table, models.ReportGeneration.__table__).create(bind=engine, checkfirst=True)

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_metadata ("
            "key VARCHAR PRIMARY KEY NOT NULL, value VARCHAR NOT NULL)"
        ))
        connection.execute(
            text(
                "INSERT INTO schema_metadata (key, value) "
                "VALUES ('schema_version', :version) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            ),
            {"version": str(CURRENT_SCHEMA_VERSION)},
        )
