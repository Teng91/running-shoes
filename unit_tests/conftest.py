# Registration is invite-only by default (SPEC-075); most tests create accounts freely.
import os

os.environ.setdefault("REGISTRATION_MODE", "open")

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.credentials import get_password_hash
from backend.database import Base
from backend.models import MonthlyMileage, Shoe, User
from unit_tests.token_helpers import create_access_token


@contextmanager
def disposing_engines() -> Iterator[list[Engine]]:
    """Dispose every engine that connects inside the block (SPEC-047)."""
    engines: list[Engine] = []

    def remember(connection):
        if connection.engine not in engines:
            engines.append(connection.engine)

    event.listen(Engine, "engine_connect", remember)
    try:
        yield engines
    finally:
        event.remove(Engine, "engine_connect", remember)
        for engine in engines:
            engine.dispose()


@pytest.fixture(autouse=True)
def dispose_test_engines():
    """Close every SQLite connection a test opened instead of leaving it to the GC."""
    with disposing_engines():
        yield


@pytest.fixture
def db(dispose_test_engines):
    # Depending on dispose_test_engines tears this session down before its engine.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolate_app_database(db, monkeypatch):
    """Keep application lifespan work on the current test's in-memory database."""
    from backend.main import app

    test_engine = db.get_bind()
    monkeypatch.setattr(app.state, "db_engine", test_engine)
    monkeypatch.setattr(app.state, "session_factory", sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    ))
    # The shared app's in-memory API budget (SPEC-073) is per test, like its database.
    from backend.middleware import ApiRequestLimiter
    monkeypatch.setattr(app.state, "api_rate_limiter", ApiRequestLimiter())


@pytest.fixture
def user_with_token(db):
    user = User(username="testuser", hashed_password=get_password_hash("pass1234"))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(data={"sub": "testuser"})
    return user, token


@pytest.fixture
def seeded_db(db):
    """一位使用者 + 5 雙鞋（使用中 4 / 退役 1）+ 近半年每月跑量。

    數值刻意對齊 test_tools.py / test_agent.py 的斷言：
      - 共 5 雙，使用中 4 / 已退役 1
      - Wave Sky 7：540/800 = 67.5%（是使用中鞋裡壽命最高的）
      - 每月跑量最後一筆為 2026-06
    回傳 (db, user_id)。
    """
    user = User(username="seeduser", hashed_password=get_password_hash("pass1234"))
    db.add(user)
    db.commit()
    db.refresh(user)

    shoes = [
        Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-09-15",
             size="us10/28cm", price=2400, orig_price=4800, mileage=540,
             expected_mileage=800, monthly_km=60, categories=["Daily"]),
        Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider 29", date="2025-12-12",
             size="us10/28cm", price=2500, orig_price=4000, mileage=293,
             expected_mileage=800, monthly_km=60, categories=["Daily"]),
        Shoe(user_id=user.id, brand="New Balance", model="Rebel v5", date="2026-02-20",
             size="us10/28cm", price=2300, orig_price=4300, mileage=102,
             expected_mileage=500, monthly_km=30, categories=["Speed"]),
        Shoe(user_id=user.id, brand="Adidas", model="Boston 12", date="2026-04-21",
             size="us10/28cm", price=1700, orig_price=4300, mileage=61,
             expected_mileage=800, monthly_km=30, categories=["Tempo"]),
        Shoe(user_id=user.id, brand="Asics", model="Gel-Excite 8", date="2024-01-05",
             size="us10/28cm", price=1800, orig_price=2300, mileage=625,
             expected_mileage=600, monthly_km=0, is_retired=True, categories=["Daily"]),
    ]
    db.add_all(shoes)

    mileage_data = [
        (2026, 1, 120.5), (2026, 2, 131.25), (2026, 3, 128.4),
        (2026, 4, 80.6), (2026, 5, 142.75), (2026, 6, 125.3),
    ]
    db.add_all([
        MonthlyMileage(user_id=user.id, year=y, month=m, km=km)
        for y, m, km in mileage_data
    ])
    db.commit()
    return db, user.id
