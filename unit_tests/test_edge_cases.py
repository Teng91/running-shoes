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


def test_lifespan_warns_and_skips_legacy_owner_migration_without_password(
    monkeypatch, caplog
):
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

    context = _run_lifespan(FastAPI())
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("shoes")}
        assert "user_id" not in columns
        assert "categories" in columns
        assert "skipping legacy schema migration" in caplog.text
    finally:
        asyncio.run(context.__aexit__(None, None, None))


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

    update = schemas.ShoeUpdate(price=None, categories=None)
    assert update.price is None
    assert update.categories is None
    with pytest.raises(ValidationError, match="Invalid categories"):
        schemas.ShoeUpdate(categories=["Other"])
    with pytest.raises(ValidationError, match="finite number"):
        schemas.ShoeUpdate(price=float("inf"))
    with pytest.raises(ValidationError, match="non-negative"):
        schemas.ShoeUpdate(monthly_km=-1)
