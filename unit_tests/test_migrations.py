import asyncio
from dataclasses import replace

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app_factory import lifespan
from backend.credentials import get_password_hash, verify_password
from backend.database import Base
from backend.migrations import run_startup_migrations
from backend.models import MonthlyMileage, Shoe, User
from backend.seeding import seed_default_data
from backend.settings import settings

# ── Seed Function Tests ─────────────────────────────────────
#
# These tests exercise seed_default_data() directly with an injected in-memory
# session factory. This isolates seed logic from the rest of the app.

def _make_test_engine():
    """Create a fresh in-memory SQLite engine with all tables created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


def _lifespan_context(engine, sessions, migration_password=None):
    app = FastAPI()
    app.state.db_engine = engine
    app.state.session_factory = sessions
    app.state.settings = replace(
        settings, seed_data=False, migration_password=migration_password
    )
    return lifespan(app)


def test_seed_disabled_when_env_not_set():
    """When SEED_DATA is not set to 'true', seed_default_data is a no-op."""
    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)
    seed_default_data(TestSession, replace(settings, seed_data=False))

    verify = TestSession()
    try:
        assert verify.query(User).count() == 0
        assert verify.query(Shoe).count() == 0
        assert verify.query(MonthlyMileage).count() == 0
    finally:
        verify.close()


def test_seed_creates_demo_and_default_data():
    """When SEED_DATA=true and DB is empty, seed creates Demo + 8 shoes + 42 mileages."""
    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)
    seed_default_data(
        TestSession,
        replace(settings, seed_data=True, migration_password="seedpass"),
    )

    verify = TestSession()
    try:
        demo = verify.query(User).filter(User.username == "Demo").first()
        assert demo is not None
        assert verify_password("seedpass", demo.hashed_password)

        # 8 shoes (6 active + 2 retired) per the seed fixture in main.py
        shoes = verify.query(Shoe).filter(Shoe.user_id == demo.id).all()
        assert len(shoes) == 8
        assert sum(1 for s in shoes if not s.is_retired) == 6
        assert sum(1 for s in shoes if s.is_retired) == 2

        # 42 monthly mileages (2023/01 ~ 2026/06)
        mileages = verify.query(MonthlyMileage).filter(MonthlyMileage.user_id == demo.id).all()
        assert len(mileages) == 25
    finally:
        verify.close()


def test_seed_does_not_overwrite_existing_data():
    """When Demo already exists with its data, seed must not modify any of it."""
    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)

    # Pre-populate Demo with one custom shoe and one custom mileage so the
    # seed's "table empty" checks both fail.
    pre = TestSession()
    try:
        demo = User(username="Demo", hashed_password=get_password_hash("existingpass"))
        pre.add(demo)
        pre.commit()
        pre.refresh(demo)

        custom_shoe = Shoe(user_id=demo.id, brand="CustomBrand", model="CustomModel",
                           date="2025-01-01", price=1000, orig_price=2000,
                           mileage=50, expected_mileage=500, monthly_km=30,
                           is_retired=False)
        pre.add(custom_shoe)

        custom_mileage = MonthlyMileage(user_id=demo.id, year=2025, month=1, km=99.99)
        pre.add(custom_mileage)
        pre.commit()

        demo_id = demo.id
        shoe_id = custom_shoe.id
        mileage_id = custom_mileage.id
    finally:
        pre.close()

    seed_default_data(
        TestSession,
        replace(settings, seed_data=True, migration_password="newpass"),
    )

    verify = TestSession()
    try:
        demo = verify.query(User).filter(User.username == "Demo").first()
        assert demo.id == demo_id
        assert verify_password("existingpass", demo.hashed_password)
        assert not verify_password("newpass", demo.hashed_password)

        # Demo's custom shoe must still exist and be unchanged
        shoe = verify.query(Shoe).filter(Shoe.id == shoe_id).first()
        assert shoe is not None
        assert shoe.brand == "CustomBrand"
        assert shoe.mileage == 50

        # Demo's custom mileage must still exist and be unchanged
        mileage = verify.query(MonthlyMileage).filter(MonthlyMileage.id == mileage_id).first()
        assert mileage is not None
        assert mileage.km == 99.99
    finally:
        verify.close()


def test_seed_raises_when_migration_password_missing():
    """If Demo doesn't exist and MIGRATION_PASSWORD isn't set, seed must raise."""
    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)
    with pytest.raises(RuntimeError, match="MIGRATION_PASSWORD"):
        seed_default_data(
            TestSession,
            replace(settings, seed_data=True, migration_password=None),
        )


# ── Lifespan Migration Tests ────────────────────────────────
#
# These tests run the lifespan async context manager directly against a test
# engine with a pre-populated old schema (shoes exists, users doesn't, no
# user_id column). They verify that lifespan migrates the schema correctly.

def test_lifespan_migrates_old_schema():
    """When DB has old schema (shoes without user_id), lifespan migrates it."""
    # Build an engine with the OLD schema only
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE shoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand VARCHAR NOT NULL,
                model VARCHAR NOT NULL,
                date VARCHAR NOT NULL,
                size VARCHAR DEFAULT '',
                price FLOAT DEFAULT 0,
                orig_price FLOAT DEFAULT 0,
                mileage FLOAT DEFAULT 0,
                expected_mileage FLOAT DEFAULT 800,
                monthly_km FLOAT DEFAULT 60,
                is_retired BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text("INSERT INTO shoes (brand, model, date) VALUES ('OldBrand', 'OldModel', '2024-01-01')"))
        conn.commit()

    async_gen = _lifespan_context(
        engine, sessionmaker(bind=engine), migration_password="migratepass"
    )
    asyncio.run(async_gen.__aenter__())

    try:
        with engine.connect() as conn:
            tables = [row[0] for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()]
            assert "users" in tables, "users table should be created during migration"

            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(shoes)")).fetchall()]
            assert "user_id" in cols, "user_id column should be added to shoes"
            assert "categories" in cols, "categories column should be added to shoes"

            user_id = conn.execute(text("SELECT user_id FROM shoes")).fetchone()[0]
            assert user_id is not None, "existing shoes should get user_id assigned"

            demo_id = conn.execute(text("SELECT id FROM users WHERE username='Demo'")).fetchone()[0]
            assert demo_id == user_id, "shoes' user_id should match Demo's id"
    finally:
        asyncio.run(async_gen.__aexit__(None, None, None))


def test_lifespan_skips_migration_when_new_schema():
    """When DB is empty or has users table, lifespan should not run migration logic."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Empty DB — no tables yet
    async_gen = _lifespan_context(engine, sessionmaker(bind=engine))
    asyncio.run(async_gen.__aenter__())

    try:
        with engine.connect() as conn:
            tables = [row[0] for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()]
            # create_all should create all tables
            assert "users" in tables
            assert "shoes" in tables
            assert "monthly_mileages" in tables
            assert "runs" in tables
            goal_columns = [row[1] for row in conn.execute(
                text("PRAGMA table_info('running_goals')")
            ).fetchall()]
            assert "version" in goal_columns
            run_indexes = [row[1] for row in conn.execute(
                text("PRAGMA index_list('runs')")
            ).fetchall()]
            assert "idx_runs_user_date" in run_indexes

            # Migration didn't run, so no Demo user should exist
            count = conn.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
            assert count == 0
    finally:
        asyncio.run(async_gen.__aexit__(None, None, None))


def test_migration_refuses_a_newer_schema_version():
    engine = _make_test_engine()
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE schema_metadata (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '99')"
        ))

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        run_startup_migrations(engine, sessionmaker(bind=engine))


def test_startup_drops_only_empty_legacy_tables():
    """SPEC-045: discontinued, unused tables go away without losing any old rows."""
    engine = _make_test_engine()
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE operation_history (id INTEGER PRIMARY KEY, user_id INTEGER, payload_json JSON)"
        ))
        connection.execute(text("CREATE INDEX idx_operation_history_user_time ON operation_history (user_id)"))
        connection.execute(text("CREATE TABLE app_settings (id INTEGER PRIMARY KEY, key VARCHAR, value VARCHAR)"))
        connection.execute(text("INSERT INTO app_settings (key, value) VALUES ('kept', 'row')"))

    run_startup_migrations(engine, sessionmaker(bind=engine))
    run_startup_migrations(engine, sessionmaker(bind=engine))

    with engine.connect() as connection:
        names = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master"))}
        assert "operation_history" not in names
        assert "idx_operation_history_user_time" not in names
        assert "app_settings" in names, "a legacy table that still holds rows is kept"
        assert connection.execute(text("SELECT value FROM app_settings")).scalar_one() == "row"
        assert connection.execute(text(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        )).scalar_one() == "15"


def test_startup_adds_the_shoe_owner_index_to_older_databases():
    """SPEC-089: databases created before the index get it at startup; queries by owner use it."""
    engine = _make_test_engine()
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX idx_shoes_user_id"))
    run_startup_migrations(engine, sessionmaker(bind=engine))
    with engine.connect() as connection:
        plan = " ".join(str(row[-1]) for row in connection.execute(
            text("EXPLAIN QUERY PLAN SELECT id FROM shoes WHERE user_id = 1 AND is_deleted = 0")))
    assert "idx_shoes_user_id" in plan, plan
    run_startup_migrations(engine, sessionmaker(bind=engine))  # idempotent


def _file_engine(tmp_path, name):
    from sqlalchemy import event

    from backend.database import configure_sqlite_connection

    engine = create_engine(f"sqlite:///{tmp_path / name}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    return engine, sessionmaker(bind=engine, autoflush=False)


def _log_run(sessions, user_id, shoe_id, day, km, activity_type="road"):
    from backend import schemas
    from backend.services.runs import create_run

    with sessions() as db:
        create_run(db, user_id, schemas.RunCreate(date=day, km=km, shoe_id=shoe_id, activity_type=activity_type),
                   max_runs=100)


def _account(sessions, name):
    with sessions() as db:
        user = User(username=name, hashed_password="synthetic")
        db.add(user)
        db.flush()
        shoe = Shoe(user_id=user.id, brand="Salomon", model="Speedcross", date="2026-01-01")
        db.add(shoe)
        db.commit()
        return user.id, shoe.id


def _month_km(engine, user_id, month):
    with engine.connect() as connection:
        return connection.execute(text(
            "SELECT km FROM monthly_mileages WHERE user_id = :u AND year = 2026 AND month = :m"
        ), {"u": user_id, "m": month}).scalar()


def test_schema_thirteen_defaults_runs_to_road(tmp_path):
    """SPEC-096 AC-1: upgrading a schema-12 database keeps every total and labels runs road."""
    from backend.migrations import schema_version

    engine, sessions = _file_engine(tmp_path, "schema12.sqlite")
    run_startup_migrations(engine, sessions)
    user_id, shoe_id = _account(sessions, "schema12-owner")
    _log_run(sessions, user_id, shoe_id, "2026-10-04", 10)
    _log_run(sessions, user_id, shoe_id, "2026-10-05", 6.5)
    with engine.begin() as connection:
        # Recreate the schema-12 runs table: no activity column, version marker 12.
        for action in ("insert", "update", "delete"):
            connection.execute(text(f"DROP TRIGGER audit_runs_{action}"))
        connection.execute(text("ALTER TABLE runs DROP COLUMN activity_type"))
        connection.execute(text("UPDATE schema_metadata SET value = '12' WHERE key = 'schema_version'"))
        shoe_before = connection.execute(text("SELECT mileage FROM shoes")).scalar()
    run_startup_migrations(engine, sessions)
    run_startup_migrations(engine, sessions)  # idempotent
    assert schema_version(engine) == 15
    with engine.connect() as connection:
        assert connection.execute(text("SELECT DISTINCT activity_type FROM runs")).scalars().all() == ["road"]
        assert connection.execute(text("SELECT mileage FROM shoes")).scalar() == shoe_before == 16.5
    assert _month_km(engine, user_id, 10) == 16.5
    _log_run(sessions, user_id, shoe_id, "2026-10-06", 4, "hike")
    assert _month_km(engine, user_id, 10) == 16.5, "new writes follow the schema-13 rule"
    engine.dispose()


def test_rollback_schema_thirteen_restores_hike_mileage(tmp_path):
    """SPEC-096 AC-9: the rollback adds hikes back to months; re-upgrading takes them out again."""
    from pathlib import Path

    from backend.migrations import schema_version

    engine, sessions = _file_engine(tmp_path, "rollback13.sqlite")
    run_startup_migrations(engine, sessions)
    user_id, shoe_id = _account(sessions, "rollback13-owner")
    other_id, other_shoe = _account(sessions, "rollback13-other")
    _log_run(sessions, user_id, shoe_id, "2026-10-04", 10)
    _log_run(sessions, user_id, shoe_id, "2026-10-11", 7.25, "hike")
    _log_run(sessions, user_id, shoe_id, "2026-11-01", 5, "hike")  # a month with hikes only
    _log_run(sessions, other_id, other_shoe, "2026-10-04", 3, "trail")
    assert (_month_km(engine, user_id, 10), _month_km(engine, user_id, 11)) == (10, None)

    script = Path("scripts/rollback_schema_thirteen.sql").read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        connection.executescript(Path("scripts/rollback_schema_fifteen.sql").read_text(encoding="utf-8"))
        connection.executescript(Path("scripts/rollback_schema_fourteen.sql").read_text(encoding="utf-8"))
        connection.executescript(script)
        with pytest.raises(Exception, match="CHECK constraint failed"):
            connection.executescript(script)
        connection.rollback()
    finally:
        connection.close()
    assert schema_version(engine) == 12
    assert (_month_km(engine, user_id, 10), _month_km(engine, user_id, 11)) == (17.25, 5)
    assert _month_km(engine, other_id, 10) == 3, "other accounts are untouched"
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT next_id > (SELECT max(id) FROM monthly_mileages) FROM entity_sequences WHERE name = 'monthly_mileages'"
        )).scalar() == 1

    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 15
    assert (_month_km(engine, user_id, 10), _month_km(engine, user_id, 11)) == (10, 0)
    assert _month_km(engine, other_id, 10) == 3
    with engine.connect() as connection:
        assert connection.execute(text("SELECT mileage FROM shoes WHERE id = :s"), {"s": shoe_id}).scalar() == 22.25
    engine.dispose()


def test_rollback_schema_thirteen_restores_walk_mileage(tmp_path):
    """SPEC-097 AC-4: walks are shoe-only too, so the rollback and re-upgrade move them like hikes."""
    from pathlib import Path

    from backend.migrations import schema_version

    engine, sessions = _file_engine(tmp_path, "rollback13-walk.sqlite")
    run_startup_migrations(engine, sessions)
    user_id, shoe_id = _account(sessions, "rollback13-walker")
    _log_run(sessions, user_id, shoe_id, "2026-10-04", 10)
    _log_run(sessions, user_id, shoe_id, "2026-10-05", 2.5, "walk")
    _log_run(sessions, user_id, shoe_id, "2026-10-06", 4, "hike")
    assert _month_km(engine, user_id, 10) == 10
    connection = engine.raw_connection()
    try:
        connection.executescript(Path("scripts/rollback_schema_fifteen.sql").read_text(encoding="utf-8"))
        connection.executescript(Path("scripts/rollback_schema_fourteen.sql").read_text(encoding="utf-8"))
        connection.executescript(Path("scripts/rollback_schema_thirteen.sql").read_text(encoding="utf-8"))
    finally:
        connection.close()
    assert schema_version(engine) == 12
    assert _month_km(engine, user_id, 10) == 16.5
    run_startup_migrations(engine, sessions)
    assert _month_km(engine, user_id, 10) == 10
    engine.dispose()


def test_schema_fourteen_adds_plan_weeks_and_rolls_back_keeping_goals(tmp_path):
    """SPEC-119: race_goals.plan_weeks is a nullable column; the rollback keeps every goal."""
    from pathlib import Path

    from backend.migrations import schema_version

    engine, sessions = _file_engine(tmp_path, "rollback14.sqlite")
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 15
    user_id, _ = _account(sessions, "rollback14-owner")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO race_goals (user_id, version, race_name, race_date, distance_km, target_seconds, plan_weeks) "
            "VALUES (:u, 1, '', '2027-03-21', 42.195, 14400, 10)"
        ), {"u": user_id})
    script = Path("scripts/rollback_schema_fourteen.sql").read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        connection.executescript(Path("scripts/rollback_schema_fifteen.sql").read_text(encoding="utf-8"))
        connection.executescript(script)
        with pytest.raises(Exception, match="CHECK constraint failed"):
            connection.executescript(script)
        connection.rollback()
    finally:
        connection.close()
    assert schema_version(engine) == 13
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 15
    with engine.connect() as connection:
        assert connection.execute(text("SELECT plan_weeks FROM race_goals WHERE user_id = :u"), {"u": user_id}).scalar() == 10
    engine.dispose()


def _account_zone(engine, user_id):
    with engine.connect() as connection:
        return connection.execute(text("SELECT timezone FROM users WHERE id = :u"), {"u": user_id}).scalar()


def test_schema_fifteen_starts_accounts_in_taipei_and_rolls_back_keeping_their_zones(tmp_path):
    """SPEC-147 AC-1: a schema-14 account starts in Asia/Taipei; the rollback keeps every saved zone."""
    from pathlib import Path

    from backend.migrations import schema_version

    engine, sessions = _file_engine(tmp_path, "rollback15.sqlite")
    run_startup_migrations(engine, sessions)
    user_id, _ = _account(sessions, "rollback15-owner")
    other_id, _ = _account(sessions, "rollback15-other")
    # The same database as schema-14 code left it: no zone column.
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE users DROP COLUMN timezone")
        connection.exec_driver_sql("UPDATE schema_metadata SET value = '14' WHERE key = 'schema_version'")
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 15
    assert (_account_zone(engine, user_id), _account_zone(engine, other_id)) == ("Asia/Taipei", "Asia/Taipei")

    with engine.begin() as connection:
        connection.execute(text("UPDATE users SET timezone = 'Asia/Tokyo' WHERE id = :u"), {"u": user_id})
    script = Path("scripts/rollback_schema_fifteen.sql").read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        connection.executescript(script)
        with pytest.raises(Exception, match="CHECK constraint failed"):
            connection.executescript(script)
        connection.rollback()
    finally:
        connection.close()
    assert schema_version(engine) == 14
    # Schema-14 code creates accounts without naming the column; they get the default zone.
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users (username, hashed_password, created_at, token_version, backup_id, data_revision) "
            "VALUES ('schema14-new', 'synthetic', '2026-11-28 00:00:00', 0, 'b14', 0)"
        ))
        new_id = connection.execute(text("SELECT id FROM users WHERE username = 'schema14-new'")).scalar()
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 15
    assert _account_zone(engine, user_id) == "Asia/Tokyo", "the upgrade reuses the saved zone"
    assert (_account_zone(engine, other_id), _account_zone(engine, new_id)) == ("Asia/Taipei", "Asia/Taipei")
    engine.dispose()
