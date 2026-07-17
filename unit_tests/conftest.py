import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import User, Shoe, MonthlyMileage
from backend.auth import get_password_hash, create_access_token


@pytest.fixture
def db():
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


@pytest.fixture
def auth_token():
    return create_access_token(data={"sub": "testuser"})


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
             size="us13/31cm", price=2390, orig_price=4780, mileage=540,
             expected_mileage=800, monthly_km=60),
        Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider 29", date="2025-12-12",
             size="us12/30cm", price=2505, orig_price=3980, mileage=293,
             expected_mileage=800, monthly_km=60),
        Shoe(user_id=user.id, brand="New Balance", model="Rebel v5", date="2026-02-20",
             size="us11/29cm", price=2300, orig_price=4280, mileage=102,
             expected_mileage=500, monthly_km=30),
        Shoe(user_id=user.id, brand="Adidas", model="Boston 12", date="2026-04-21",
             size="us11.5/29.5cm", price=1680, orig_price=4290, mileage=61,
             expected_mileage=800, monthly_km=30),
        Shoe(user_id=user.id, brand="Asics", model="Gel-Excite 8", date="2024-01-05",
             size="us11/29cm", price=1780, orig_price=2280, mileage=625,
             expected_mileage=600, monthly_km=0, is_retired=True),
    ]
    db.add_all(shoes)

    mileage_data = [
        (2026, 1, 125.71), (2026, 2, 135.91), (2026, 3, 130.13),
        (2026, 4, 78.41), (2026, 5, 149.12), (2026, 6, 128.2),
    ]
    db.add_all([
        MonthlyMileage(user_id=user.id, year=y, month=m, km=km)
        for y, m, km in mileage_data
    ])
    db.commit()
    return db, user.id
