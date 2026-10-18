import asyncio
from dataclasses import replace

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app_factory import lifespan
from backend.auth import get_password_hash, verify_password
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


def test_seed_creates_joy_and_default_data():
    """When SEED_DATA=true and DB is empty, seed creates Joy + 8 shoes + 42 mileages."""
    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)
    seed_default_data(
        TestSession,
        replace(settings, seed_data=True, migration_password="seedpass"),
    )

    verify = TestSession()
    try:
        joy = verify.query(User).filter(User.username == "Joy").first()
        assert joy is not None
        assert verify_password("seedpass", joy.hashed_password)

        # 8 shoes (6 active + 2 retired) per the seed fixture in main.py
        shoes = verify.query(Shoe).filter(Shoe.user_id == joy.id).all()
        assert len(shoes) == 8
        assert sum(1 for s in shoes if not s.is_retired) == 6
        assert sum(1 for s in shoes if s.is_retired) == 2

        # 42 monthly mileages (2023/01 ~ 2026/06)
        mileages = verify.query(MonthlyMileage).filter(MonthlyMileage.user_id == joy.id).all()
        assert len(mileages) == 42
    finally:
        verify.close()


def test_seed_does_not_overwrite_existing_data():
    """When Joy already exists with her data, seed must not modify any of it."""
    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)

    # Pre-populate Joy with one custom shoe and one custom mileage so the
    # seed's "table empty" checks both fail.
    pre = TestSession()
    try:
        joy = User(username="Joy", hashed_password=get_password_hash("existingpass"))
        pre.add(joy)
        pre.commit()
        pre.refresh(joy)

        custom_shoe = Shoe(user_id=joy.id, brand="CustomBrand", model="CustomModel",
                           date="2025-01-01", price=1000, orig_price=2000,
                           mileage=50, expected_mileage=500, monthly_km=30,
                           is_retired=False)
        pre.add(custom_shoe)

        custom_mileage = MonthlyMileage(user_id=joy.id, year=2025, month=1, km=99.99)
        pre.add(custom_mileage)
        pre.commit()

        joy_id = joy.id
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
        joy = verify.query(User).filter(User.username == "Joy").first()
        assert joy.id == joy_id
        assert verify_password("existingpass", joy.hashed_password)
        assert not verify_password("newpass", joy.hashed_password)

        # Joy's custom shoe must still exist and be unchanged
        shoe = verify.query(Shoe).filter(Shoe.id == shoe_id).first()
        assert shoe is not None
        assert shoe.brand == "CustomBrand"
        assert shoe.mileage == 50

        # Joy's custom mileage must still exist and be unchanged
        mileage = verify.query(MonthlyMileage).filter(MonthlyMileage.id == mileage_id).first()
        assert mileage is not None
        assert mileage.km == 99.99
    finally:
        verify.close()


def test_seed_raises_when_migration_password_missing():
    """If Joy doesn't exist and MIGRATION_PASSWORD isn't set, seed must raise."""
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

            joy_id = conn.execute(text("SELECT id FROM users WHERE username='Joy'")).fetchone()[0]
            assert joy_id == user_id, "shoes' user_id should match Joy's id"
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

            # Migration didn't run, so no Joy user should exist
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
