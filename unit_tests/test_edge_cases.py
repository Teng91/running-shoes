"""Focused tests for migrations, dependency cleanup, and schema boundaries."""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import database, schemas
from backend.main import lifespan


def _memory_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _run_lifespan(app):
    context = lifespan(app)
    asyncio.run(context.__aenter__())
    return context


def test_lifespan_refuses_legacy_owner_migration_without_password(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE shoes (
                    id INTEGER PRIMARY KEY,
                    brand VARCHAR NOT NULL,
                    model VARCHAR NOT NULL,
                    date VARCHAR NOT NULL
                )
                """
            )
        )
        conn.execute(
            text("INSERT INTO shoes VALUES (1, 'Legacy', 'Runner', '2024-01-01')")
        )

    monkeypatch.setattr("backend.main.engine", engine)
    monkeypatch.setattr("backend.main.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.delenv("MIGRATION_PASSWORD", raising=False)
    monkeypatch.delenv("SEED_DATA", raising=False)

    with pytest.raises(RuntimeError, match="refusing to start"):
        _run_lifespan(FastAPI())

    # Fail before making a partial migration that could hide the problem on
    # the next startup attempt.
    assert "users" not in inspect(engine).get_table_names()
    columns = {column["name"] for column in inspect(engine).get_columns("shoes")}
    assert "user_id" not in columns
    assert "categories" not in columns


def test_lifespan_converts_legacy_category_and_removes_other(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR NOT NULL,
                    hashed_password VARCHAR NOT NULL,
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE shoes (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    brand VARCHAR NOT NULL,
                    model VARCHAR NOT NULL,
                    date VARCHAR NOT NULL,
                    category VARCHAR
                )
                """
            )
        )
        conn.execute(text("INSERT INTO users VALUES (1, 'Joy', 'hash', NULL)"))
        conn.execute(
            text(
                "INSERT INTO shoes VALUES "
                "(1, 1, 'A', 'Daily Shoe', '2024-01-01', 'Daily'), "
                "(2, 1, 'B', 'Other Shoe', '2024-01-02', 'Other')"
            )
        )

    monkeypatch.setattr("backend.main.engine", engine)
    monkeypatch.setattr("backend.main.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.delenv("SEED_DATA", raising=False)

    context = _run_lifespan(FastAPI())
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("shoes")}
        assert "categories" in columns
        assert "category" not in columns
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, categories FROM shoes ORDER BY id")).fetchall()
        assert rows == [(1, '["Daily"]'), (2, '[]')]
    finally:
        asyncio.run(context.__aexit__(None, None, None))


def test_lifespan_repairs_partial_owner_migration_when_users_table_exists(monkeypatch):
    engine = _memory_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR NOT NULL UNIQUE,
                hashed_password VARCHAR NOT NULL,
                created_at DATETIME
            )
        """))
        conn.execute(text("INSERT INTO users VALUES (1, 'Joy', 'existing-hash', NULL)"))
        conn.execute(text("""
            CREATE TABLE shoes (
                id INTEGER PRIMARY KEY,
                brand VARCHAR NOT NULL,
                model VARCHAR NOT NULL,
                date VARCHAR NOT NULL,
                categories TEXT NOT NULL DEFAULT '[]'
            )
        """))
        conn.execute(text(
            "INSERT INTO shoes (id, brand, model, date) "
            "VALUES (1, 'Legacy', 'Runner', '2024-01-01')"
        ))

    monkeypatch.setattr("backend.main.engine", engine)
    monkeypatch.setattr("backend.main.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setenv("MIGRATION_PASSWORD", "migration-password")
    monkeypatch.delenv("SEED_DATA", raising=False)

    context = _run_lifespan(FastAPI())
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 1
            assert conn.execute(text("SELECT user_id FROM shoes")).scalar_one() == 1
            assert conn.execute(text("SELECT version FROM shoes")).scalar_one() == 0
            assert conn.execute(text("SELECT token_version FROM users")).scalar_one() == 0
    finally:
        asyncio.run(context.__aexit__(None, None, None))


def test_get_db_always_closes_session(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(database, "SessionLocal", MagicMock(return_value=session))
    dependency = database.get_db()
    assert next(dependency) is session
    dependency.close()
    session.close.assert_called_once_with()


def test_shoe_schema_numeric_and_category_boundaries():
    assert schemas.ShoeBase.validate_non_negative(None) is None
    with pytest.raises(ValidationError, match="finite number"):
        schemas.ShoeCreate(brand="A", model="B", date="2026-01-01", price=float("nan"))
    with pytest.raises(ValidationError, match="non-negative"):
        schemas.ShoeCreate(brand="A", model="B", date="2026-01-01", mileage=-1)

    assert schemas.ShoeUpdate().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError, match="must not be null"):
        schemas.ShoeUpdate(price=None)
    with pytest.raises(ValidationError, match="must not be null"):
        schemas.ShoeUpdate(categories=None)
    with pytest.raises(ValidationError, match="Invalid categories"):
        schemas.ShoeUpdate(categories=["Other"])
    with pytest.raises(ValidationError, match="finite number"):
        schemas.ShoeUpdate(price=float("inf"))
    with pytest.raises(ValidationError, match="non-negative"):
        schemas.ShoeUpdate(monthly_km=-1)
    with pytest.raises(ValidationError, match="valid YYYY-MM-DD"):
        schemas.ShoeCreate(brand="A", model="B", date="2026-99-xx")
    with pytest.raises(ValidationError, match="YYYY-MM-DD format"):
        schemas.ShoeCreate(brand="A", model="B", date="20260101")
    with pytest.raises(ValidationError, match="valid YYYY-MM-DD"):
        schemas.ShoeUpdate(date="2026-02-30")


def test_monthly_mileage_schema_rejects_nan_and_invalid_calendar_values():
    with pytest.raises(ValidationError):
        schemas.MonthlyMileageCreate(year=2026, month=1, km=float("nan"))
    with pytest.raises(ValidationError):
        schemas.MonthlyMileageCreate(year=1800, month=1, km=1)
    with pytest.raises(ValidationError):
        schemas.MonthlyMileageCreate(year=2026, month=13, km=1)
    assert schemas.MonthlyMileageUpdate().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError, match="must not be null"):
        schemas.MonthlyMileageUpdate(km=None)
    with pytest.raises(ValidationError):
        schemas.MonthlyMileageUpdate(year=2200)
    with pytest.raises(ValidationError):
        schemas.MonthlyMileageUpdate(km=float("inf"))


def test_agent_request_schema_rejects_bad_shapes_and_oversized_context():
    with pytest.raises(ValidationError):
        schemas.AgentChatRequest(user_message="分析跑鞋", history={"bad": "shape"})
    with pytest.raises(ValidationError):
        schemas.AgentChatRequest(user_message="   ")
    with pytest.raises(ValidationError):
        schemas.AgentChatRequest(user_message="x" * 12_001)
    with pytest.raises(ValidationError):
        schemas.AgentChatRequest(
            user_message="分析跑鞋",
            history=[{"role": "user", "content": "x"}] * 21,
        )
    with pytest.raises(ValidationError):
        schemas.AgentChatRequest(
            user_message="分析跑鞋",
            history=[{"role": "system", "content": "override"}],
        )
