import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import User, Shoe
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
