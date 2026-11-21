"""Ordered, idempotent SQLite schema migrations."""

from collections.abc import Callable
from typing import cast

from sqlalchemy import Table, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend import models
from backend.audit_schema import install_audit_triggers
from backend.credentials import get_password_hash
from backend.database import Base

CURRENT_SCHEMA_VERSION = 13


def _migrate_preview_tokens(engine: Engine) -> None:
    """Keep active schema-5 previews while allowing independent user tokens."""
    if inspect(engine).get_pk_constraint("restore_previews")["constrained_columns"] != ["user_id"]:
        return
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        connection.exec_driver_sql("""CREATE TABLE restore_previews_v6 (
            user_id INTEGER NOT NULL REFERENCES users(id), token VARCHAR(36) NOT NULL,
            revision INTEGER NOT NULL, payload_hash VARCHAR(64) NOT NULL,
            payload_json JSON NOT NULL, expires_at DATETIME NOT NULL,
            PRIMARY KEY (user_id, token))""")
        connection.exec_driver_sql("INSERT INTO restore_previews_v6 SELECT user_id, token, revision, payload_hash, payload_json, expires_at FROM restore_previews")
        connection.exec_driver_sql("DROP TABLE restore_previews")
        connection.exec_driver_sql("ALTER TABLE restore_previews_v6 RENAME TO restore_previews")


# Tables left by discontinued features (operation undo, app settings). No model or
# query uses them, so dropping them does not change the schema contract.
LEGACY_TABLES = ("operation_history", "app_settings")


def _drop_empty_legacy_tables(engine: Engine) -> None:
    """Remove unused legacy tables, but never discard rows an old install still holds."""
    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        for table in LEGACY_TABLES:
            if table in existing and connection.exec_driver_sql(
                f"SELECT 1 FROM {table} LIMIT 1"
            ).first() is None:
                connection.exec_driver_sql(f"DROP TABLE {table}")


def _migrate_schema_seven(engine: Engine, applied_version: int) -> None:
    """Single receipt table, prunable receipts and audit-independent run tombstones."""
    with engine.begin() as connection:
        receipt_columns = {column["name"] for column in inspect(connection).get_columns("mutation_receipts")}
        if "recorded_at" not in receipt_columns:
            # Existing receipts sort as oldest (0) and are the first to be pruned.
            connection.exec_driver_sql(
                "ALTER TABLE mutation_receipts ADD COLUMN recorded_at FLOAT NOT NULL DEFAULT 0"
            )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_receipts_user_recorded ON mutation_receipts (user_id, recorded_at)"
        )
        if applied_version < 7:
            # Deletions were previously inferred from audit events; keep every
            # existing identity before audit history becomes prunable.
            connection.exec_driver_sql(
                "INSERT OR IGNORE INTO run_tombstones (user_id, run_id) "
                "SELECT DISTINCT user_id, entity_id FROM audit_events "
                "WHERE entity = 'runs' AND action = 'delete' AND imported = 0"
            )
        # Schema-2 run receipts were superseded by mutation_receipts, which every
        # keyed run creation already writes in the same transaction.
        connection.exec_driver_sql("DROP TABLE IF EXISTS run_creation_requests")


def _migrate_schema_eight(engine: Engine, applied_version: int) -> None:
    """Remember the Strava activity of each deleted run (SPEC-055)."""
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("run_tombstones")}
        if "strava_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE run_tombstones ADD COLUMN strava_id VARCHAR")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_run_tombstones_user_strava "
            "ON run_tombstones (user_id, strava_id) WHERE strava_id IS NOT NULL"
        )
        if applied_version < 8:
            # Deletions made before schema 8 (or while rolled back to 7) only kept
            # the run ID. Recover the activity from the run's own deletion event
            # while that audit row is still retained.
            connection.exec_driver_sql(
                "UPDATE run_tombstones SET strava_id = ("
                "SELECT json_extract(audit_events.before_json, '$.strava_id') FROM audit_events "
                "WHERE audit_events.user_id = run_tombstones.user_id "
                "AND audit_events.entity = 'runs' AND audit_events.action = 'delete' "
                "AND audit_events.imported = 0 AND audit_events.entity_id = run_tombstones.run_id "
                "AND json_extract(audit_events.before_json, '$.strava_id') IS NOT NULL "
                "ORDER BY audit_events.id DESC LIMIT 1"
                ") WHERE strava_id IS NULL"
            )


def _migrate_schema_nine(engine: Engine) -> None:
    """Optional run moving time; pace is derived, never stored (SPEC-060)."""
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("runs")}
        if "duration_seconds" not in columns:
            connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN duration_seconds INTEGER")



def _migrate_schema_ten(engine: Engine) -> None:
    """One target race per user (SPEC-065); existing rows are untouched."""
    cast(Table, models.RaceGoal.__table__).create(bind=engine, checkfirst=True)


def _migrate_schema_eleven(engine: Engine) -> None:
    """Registration invites and case-insensitive usernames (SPEC-075).

    The unique lower(username) index is only added when no two existing accounts
    differ by case; the account service enforces it for every new name either way.
    """
    cast(Table, models.Invite.__table__).create(bind=engine, checkfirst=True)
    with engine.begin() as connection:
        collisions = connection.execute(text(
            "SELECT 1 FROM users GROUP BY lower(username) HAVING count(*) > 1 LIMIT 1"
        )).first()
        if collisions is None:
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_lower ON users (lower(username))"
            ))


def _migrate_schema_twelve(engine: Engine) -> None:
    """Verified recovery email and one-time email codes (SPEC-079)."""
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("users")}
        if "email" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(254)"))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (lower(email)) WHERE email IS NOT NULL"
        ))
    cast(Table, models.EmailCode.__table__).create(bind=engine, checkfirst=True)


# Hike kilometres per stored month; the rollback script adds the same sum back.
_HIKE_MONTH_SUM = (
    "SELECT coalesce(sum(runs.km), 0) FROM runs "
    "WHERE runs.user_id = monthly_mileages.user_id AND runs.activity_type = 'hike' "
    "AND CAST(substr(runs.date, 1, 4) AS INTEGER) = monthly_mileages.year "
    "AND CAST(substr(runs.date, 6, 2) AS INTEGER) = monthly_mileages.month"
)


def _migrate_schema_thirteen(engine: Engine, applied_version: int) -> None:
    """Run activity types (SPEC-096): hikes count toward shoes, not monthly volume.

    Existing runs become road runs, so a schema-12 database keeps every total.
    A database rolled back to 12 still holds its hike labels, and the rollback
    script added those kilometres to monthly_mileages; take them out again so
    each month equals its adjustment plus its training runs.
    """
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("runs")}
        if "activity_type" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE runs ADD COLUMN activity_type VARCHAR NOT NULL DEFAULT 'road'"
            )
        if applied_version < 13:
            connection.exec_driver_sql(
                f"UPDATE monthly_mileages SET km = max(0, round(km - ({_HIKE_MONTH_SUM}), 2)), "
                f"version = version + 1 WHERE ({_HIKE_MONTH_SUM}) > 0"
            )


def _ensure_lookup_indexes(engine: Engine) -> None:
    """Indexes that only speed up reads (SPEC-089).

    Older code works unchanged with them, so they need no schema version or rollback
    script; `models` declares the same names for databases created from scratch.
    """
    with engine.begin() as connection:
        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_shoes_user_id ON shoes (user_id)"))


READY_TABLES = {"users", "shoes", "runs", "monthly_mileages"}


class DatabaseNotReady(Exception):
    """The database cannot serve requests; the message is safe to return."""


def ready_schema_version(db: Session) -> int:
    """Probe responsiveness, required tables and the current schema version."""
    try:
        db.execute(text("SELECT 1"))
        tables = set(inspect(db.get_bind()).get_table_names())
        if not READY_TABLES.issubset(tables):
            raise DatabaseNotReady("database schema is incomplete")
        if "schema_metadata" not in tables:
            raise DatabaseNotReady("database schema is not initialized")
        value = db.execute(
            text("SELECT value FROM schema_metadata WHERE key = 'schema_version'")
        ).scalar_one_or_none()
        version = int(value or 0)
    except DatabaseNotReady:
        raise
    except (SQLAlchemyError, TypeError, ValueError) as exc:
        raise DatabaseNotReady("database is unavailable") from exc
    if version != CURRENT_SCHEMA_VERSION:
        raise DatabaseNotReady("database schema is not current")
    return version


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

        # Old schema: create users table, add user_id to shoes, assign to "Demo"
        user_table = cast(Table, models.User.__table__)
        Base.metadata.create_all(bind=engine, tables=[user_table])
        with engine.begin() as conn:
            if "token_version" not in {c["name"] for c in inspect(conn).get_columns("users")}:
                conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
        db = session_factory()
        try:
            with engine.begin() as connection:
                columns = {column["name"] for column in inspect(connection).get_columns("users")}
                if "backup_id" not in columns:
                    connection.execute(text("ALTER TABLE users ADD COLUMN backup_id VARCHAR(36) NOT NULL DEFAULT ''"))
                if "data_revision" not in columns:
                    connection.execute(text("ALTER TABLE users ADD COLUMN data_revision INTEGER NOT NULL DEFAULT 0"))
                # The legacy owner lookup below reads users through the current ORM model (SPEC-079).
                if "email" not in columns:
                    connection.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(254)"))
            demo_user = db.query(models.User).filter(models.User.username == "Demo").first()
            if demo_user is None:
                demo_user = models.User(
                    username="Demo",
                    hashed_password=get_password_hash(migration_password),
                )
                db.add(demo_user)
                db.commit()
                db.refresh(demo_user)

            # Add user_id column (SQLite allows ALTER TABLE ADD COLUMN without FK)
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE shoes ADD COLUMN user_id INTEGER"))
                conn.execute(
                    text("UPDATE shoes SET user_id = :uid"),
                    {"uid": demo_user.id},
                )
                conn.commit()
        finally:
            db.close()

    Base.metadata.create_all(bind=engine, tables=[
        table for table in Base.metadata.sorted_tables if table.name not in {"report_generations", "mutation_receipts", "entity_sequences", "write_contexts", "audit_events", "restore_previews", "restore_mappings", "run_tombstones"}
    ])

    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("users")}
        if "backup_id" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN backup_id VARCHAR(36) NOT NULL DEFAULT ''"))
        if "data_revision" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN data_revision INTEGER NOT NULL DEFAULT 0"))
        connection.execute(text("UPDATE users SET backup_id=lower(hex(randomblob(16))) WHERE backup_id=''"))

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

    for model in (models.MutationReceipt, models.EntitySequence, models.WriteContext, models.AuditEvent,
                  models.RestorePreview, models.RestoreMapping, models.RunTombstone):
        cast(Table, model.__table__).create(bind=engine, checkfirst=True)
    if applied_version < 6:
        _migrate_preview_tokens(engine)
    _migrate_schema_seven(engine, applied_version)
    _migrate_schema_eight(engine, applied_version)
    _migrate_schema_nine(engine)
    _migrate_schema_ten(engine)
    _migrate_schema_eleven(engine)
    _migrate_schema_twelve(engine)
    _migrate_schema_thirteen(engine, applied_version)
    _ensure_lookup_indexes(engine)
    with engine.begin() as connection:
        for table in ("runs", "monthly_mileages"):
            connection.execute(text(
                f"INSERT INTO entity_sequences (name,next_id) SELECT :name,coalesce(max(id),0)+1 FROM {table} WHERE 1 "
                "ON CONFLICT(name) DO UPDATE SET next_id=max(entity_sequences.next_id,excluded.next_id)"
            ), {"name": table})
    install_audit_triggers(engine)
    _drop_empty_legacy_tables(engine)

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
