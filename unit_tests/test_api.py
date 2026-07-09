import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import User, Shoe, MonthlyMileage
from backend.auth import get_password_hash, verify_password
from backend.main import app


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Auth Tests ────────────────────────────────────────────────

def test_register_success(client):
    res = client.post("/api/auth/register", json={"username": "alice", "password": "pass1234"})
    assert res.status_code == 200
    assert res.json()["username"] == "alice"


def test_register_short_password(client):
    res = client.post("/api/auth/register", json={"username": "alice", "password": "ab"})
    assert res.status_code == 400
    assert "4 characters" in res.json()["detail"]


def test_register_duplicate_username(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("pass1234")))
    db.commit()
    res = client.post("/api/auth/register", json={"username": "alice", "password": "pass1234"})
    assert res.status_code == 400


def test_login_success(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("pass1234")))
    db.commit()
    res = client.post("/api/auth/login", json={"username": "alice", "password": "pass1234"})
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_login_user_not_found(client):
    res = client.post("/api/auth/login", json={"username": "nobody", "password": "pass1234"})
    assert res.status_code == 404
    assert res.json()["detail"] == "User not found"


def test_login_wrong_password(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("pass1234")))
    db.commit()
    res = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect password"


def test_change_password(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "oldpass", "new_password": "newpass1",
    })
    assert res.status_code == 200
    # Verify new password works
    res = client.post("/api/auth/login", json={"username": "alice", "password": "newpass1"})
    assert res.status_code == 200


def test_change_password_user_not_found(client):
    res = client.post("/api/auth/change-password", json={
        "username": "nobody", "old_password": "oldpass", "new_password": "newpass1",
    })
    assert res.status_code == 404


def test_change_password_wrong_old(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "wrong", "new_password": "newpass1",
    })
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect old password"


def test_change_password_short_new(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "oldpass", "new_password": "ab",
    })
    assert res.status_code == 400


def test_change_password_empty_old(client, db):
    """Empty old_password should be treated as wrong password (401), not crash."""
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "", "new_password": "newpass1",
    })
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect old password"


def test_change_password_empty_new(client, db):
    """Empty new_password should fail the length check (400)."""
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "oldpass", "new_password": "",
    })
    assert res.status_code == 400
    assert "4 characters" in res.json()["detail"]


def test_change_password_same_as_old(client, db):
    """Changing to the same password is allowed (no-op effectively)."""
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "oldpass", "new_password": "oldpass",
    })
    assert res.status_code == 200


def test_change_password_chained(client, db):
    """After changing password, the new password works as old_password for subsequent changes."""
    db.add(User(username="alice", hashed_password=get_password_hash("pass1")))
    db.commit()
    # First change
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "pass1", "new_password": "pass2",
    })
    assert res.status_code == 200
    # Second change must use pass2 as old_password
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "pass1", "new_password": "pass3",
    })
    assert res.status_code == 401  # pass1 no longer valid
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "pass2", "new_password": "pass3",
    })
    assert res.status_code == 200


def test_get_me_authenticated(client, user_with_token):
    """GET /api/auth/me returns the current user's info."""
    user, token = user_with_token
    res = client.get("/api/auth/me", headers=_auth_header(token))
    assert res.status_code == 200
    assert res.json()["username"] == "testuser"


def test_get_me_unauthenticated(client):
    """GET /api/auth/me without a token returns 401/403."""
    res = client.get("/api/auth/me")
    assert res.status_code in (401, 403)


# ── Static File / Path Traversal Tests ───────────────────────

def test_path_traversal_returns_spa_fallback(client):
    """Malicious paths must not leak files outside frontend_dir.

    The 404 handler should resolve the path and check it's inside frontend_dir;
    if not, fall back to index.html instead of serving arbitrary files.
    """
    for path in [
        "/../backend/main.py",   # try to escape to backend source
        "/../../etc/passwd",     # try system file
        "/../shoes.db",          # try the DB file
    ]:
        res = client.get(path)
        # Either properly rejected with 404, OR served the SPA fallback (index.html).
        # What it MUST NOT do: serve the requested file's content.
        if res.status_code == 200:
            # If 200, response should be index.html (HTML), not the target file
            assert "text/html" in res.headers.get("content-type", ""), \
                f"{path} returned 200 with non-HTML content-type"
        else:
            assert res.status_code == 404, f"{path} returned unexpected {res.status_code}"


def test_api_404_returns_json_not_html(client):
    """Unknown /api/* paths should return JSON 404, not the SPA fallback."""
    res = client.get("/api/nonexistent-endpoint")
    assert res.status_code == 404
    assert "application/json" in res.headers.get("content-type", "")
    assert "detail" in res.json()


# ── Shoe CRUD Tests ───────────────────────────────────────────

def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_list_active_shoes(client, user_with_token):
    user, token = user_with_token
    res = client.get("/api/shoes/active", headers=_auth_header(token))
    assert res.status_code == 200
    assert res.json() == []


def test_create_shoe(client, db, user_with_token):
    user, token = user_with_token
    res = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "Mizuno", "model": "Wave Sky 7", "date": "2024-01-01",
        "price": 2390, "orig_price": 4780, "mileage": 100,
        "expected_mileage": 800, "monthly_km": 60,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["brand"] == "Mizuno"
    assert data["user_id"] == user.id


def test_update_shoe(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01",
                price=2390, orig_price=4780, mileage=100, expected_mileage=800, monthly_km=60)
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    res = client.put(f"/api/shoes/{shoe.id}", headers=_auth_header(token), json={"mileage": 200})
    assert res.status_code == 200
    assert res.json()["mileage"] == 200


def test_delete_shoe(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01",
                price=2390, orig_price=4780, mileage=100, expected_mileage=800, monthly_km=60)
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    res = client.delete(f"/api/shoes/{shoe.id}", headers=_auth_header(token))
    assert res.status_code == 200


def test_shoe_isolation_between_users(client, db):
    user_a = User(username="alice", hashed_password=get_password_hash("pass1234"))
    user_b = User(username="bob", hashed_password=get_password_hash("pass1234"))
    db.add_all([user_a, user_b])
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    shoe = Shoe(user_id=user_a.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01",
               price=2390, orig_price=4780, mileage=100, expected_mileage=800, monthly_km=60)
    db.add(shoe)
    db.commit()

    from backend.auth import create_access_token
    token_b = create_access_token(data={"sub": "bob"})

    # Bob cannot see Alice's shoes
    res = client.get("/api/shoes/active", headers=_auth_header(token_b))
    assert res.json() == []

    # Bob cannot delete Alice's shoe
    db.refresh(shoe)
    res = client.delete(f"/api/shoes/{shoe.id}", headers=_auth_header(token_b))
    assert res.status_code == 404


def test_list_retired_shoes(client, db, user_with_token):
    """GET /api/shoes/retired returns only retired shoes (not active ones)."""
    user, token = user_with_token
    db.add(Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01",
                price=2390, orig_price=4780, mileage=100, expected_mileage=800,
                monthly_km=60, is_retired=False))
    db.add(Shoe(user_id=user.id, brand="Asics", model="Gel-Excite 8", date="2023-01-01",
                price=1780, orig_price=2280, mileage=625, expected_mileage=600,
                monthly_km=0, is_retired=True))
    db.commit()

    res = client.get("/api/shoes/retired", headers=_auth_header(token))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["model"] == "Gel-Excite 8"
    assert data[0]["is_retired"] is True


def test_unauthenticated_access(client):
    res = client.get("/api/shoes/active")
    assert res.status_code == 401  # No credentials provided


# ── Monthly Mileage CRUD Tests ────────────────────────────────

def test_list_monthly_mileage_empty(client, user_with_token):
    user, token = user_with_token
    res = client.get("/api/monthly-mileage", headers=_auth_header(token))
    assert res.status_code == 200
    assert res.json() == []


def test_list_monthly_mileage_with_data(client, db, user_with_token):
    """GET /api/monthly-mileage returns entries ordered by year, then month."""
    user, token = user_with_token
    db.add(MonthlyMileage(user_id=user.id, year=2026, month=1, km=125.71))
    db.add(MonthlyMileage(user_id=user.id, year=2025, month=12, km=196.32))
    db.commit()

    res = client.get("/api/monthly-mileage", headers=_auth_header(token))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    # Ordered by (year, month)
    assert data[0]["year"] == 2025 and data[0]["month"] == 12
    assert data[1]["year"] == 2026 and data[1]["month"] == 1


def test_create_monthly_mileage(client, db, user_with_token):
    user, token = user_with_token
    res = client.post("/api/monthly-mileage", headers=_auth_header(token), json={
        "year": 2026, "month": 7, "km": 100.5,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["year"] == 2026
    assert data["month"] == 7
    assert data["km"] == 100.5
    assert data["user_id"] == user.id


def test_create_monthly_mileage_invalid_month(client, user_with_token):
    user, token = user_with_token
    res = client.post("/api/monthly-mileage", headers=_auth_header(token), json={
        "year": 2026, "month": 13, "km": 10,
    })
    assert res.status_code == 400


def test_create_monthly_mileage_duplicate(client, db, user_with_token):
    user, token = user_with_token
    db.add(MonthlyMileage(user_id=user.id, year=2026, month=7, km=50))
    db.commit()
    res = client.post("/api/monthly-mileage", headers=_auth_header(token), json={
        "year": 2026, "month": 7, "km": 100,
    })
    assert res.status_code == 400
    assert "已有紀錄" in res.json()["detail"]


def test_update_monthly_mileage(client, db, user_with_token):
    user, token = user_with_token
    entry = MonthlyMileage(user_id=user.id, year=2026, month=7, km=50)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    res = client.put(f"/api/monthly-mileage/{entry.id}", headers=_auth_header(token), json={"km": 75.5})
    assert res.status_code == 200
    assert res.json()["km"] == 75.5


def test_update_monthly_mileage_not_found(client, user_with_token):
    user, token = user_with_token
    res = client.put("/api/monthly-mileage/99999", headers=_auth_header(token), json={"km": 10})
    assert res.status_code == 404


def test_update_monthly_mileage_clash(client, db, user_with_token):
    user, token = user_with_token
    e1 = MonthlyMileage(user_id=user.id, year=2026, month=7, km=50)
    e2 = MonthlyMileage(user_id=user.id, year=2026, month=8, km=60)
    db.add_all([e1, e2])
    db.commit()
    db.refresh(e1)
    res = client.put(f"/api/monthly-mileage/{e1.id}", headers=_auth_header(token), json={"month": 8})
    assert res.status_code == 400


def test_delete_monthly_mileage(client, db, user_with_token):
    user, token = user_with_token
    entry = MonthlyMileage(user_id=user.id, year=2026, month=7, km=50)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    res = client.delete(f"/api/monthly-mileage/{entry.id}", headers=_auth_header(token))
    assert res.status_code == 200
    # Verify it's gone
    res = client.get("/api/monthly-mileage", headers=_auth_header(token))
    assert res.json() == []


def test_monthly_mileage_isolation_between_users(client, db):
    user_a = User(username="alice", hashed_password=get_password_hash("pass1234"))
    user_b = User(username="bob", hashed_password=get_password_hash("pass1234"))
    db.add_all([user_a, user_b])
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    entry = MonthlyMileage(user_id=user_a.id, year=2026, month=7, km=50)
    db.add(entry)
    db.commit()
    db.refresh(entry)

    from backend.auth import create_access_token
    token_b = create_access_token(data={"sub": "bob"})

    # Bob cannot see Alice's monthly mileage
    res = client.get("/api/monthly-mileage", headers=_auth_header(token_b))
    assert res.json() == []

    # Bob cannot delete Alice's monthly mileage
    res = client.delete(f"/api/monthly-mileage/{entry.id}", headers=_auth_header(token_b))
    assert res.status_code == 404


def test_monthly_mileage_unauthenticated(client):
    res = client.get("/api/monthly-mileage")
    assert res.status_code == 401


# ── Seed Function Tests ─────────────────────────────────────
#
# These tests exercise seed_default_data() directly. They bypass the lifespan /
# app startup by patching backend.main.SessionLocal to point at a fresh in-memory
# test engine. This isolates seed logic from the rest of the app.

def _make_test_engine():
    """Create a fresh in-memory SQLite engine with all tables created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


def test_seed_disabled_when_env_not_set(monkeypatch):
    """When SEED_DATA is not set to 'true', seed_default_data is a no-op."""
    monkeypatch.delenv("SEED_DATA", raising=False)

    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr("backend.main.SessionLocal", TestSession)

    from backend.main import seed_default_data
    seed_default_data()

    verify = TestSession()
    try:
        assert verify.query(User).count() == 0
        assert verify.query(Shoe).count() == 0
        assert verify.query(MonthlyMileage).count() == 0
    finally:
        verify.close()


def test_seed_creates_joy_and_default_data(monkeypatch):
    """When SEED_DATA=true and DB is empty, seed creates Joy + 8 shoes + 42 mileages."""
    monkeypatch.setenv("SEED_DATA", "true")
    monkeypatch.setenv("MIGRATION_PASSWORD", "seedpass")

    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr("backend.main.SessionLocal", TestSession)

    from backend.main import seed_default_data
    seed_default_data()

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


def test_seed_does_not_overwrite_existing_data(monkeypatch):
    """When Joy already exists with her data, seed must not modify any of it."""
    monkeypatch.setenv("SEED_DATA", "true")
    monkeypatch.setenv("MIGRATION_PASSWORD", "newpass")

    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr("backend.main.SessionLocal", TestSession)

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

    from backend.main import seed_default_data
    seed_default_data()

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


def test_seed_raises_when_migration_password_missing(monkeypatch):
    """If Joy doesn't exist and MIGRATION_PASSWORD isn't set, seed must raise."""
    monkeypatch.setenv("SEED_DATA", "true")
    monkeypatch.delenv("MIGRATION_PASSWORD", raising=False)

    engine = _make_test_engine()
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr("backend.main.SessionLocal", TestSession)

    from backend.main import seed_default_data
    with pytest.raises(RuntimeError, match="MIGRATION_PASSWORD"):
        seed_default_data()


# ── Lifespan Migration Tests ────────────────────────────────
#
# These tests run the lifespan async context manager directly against a test
# engine with a pre-populated old schema (shoes exists, users doesn't, no
# user_id column). They verify that lifespan migrates the schema correctly.

def test_lifespan_migrates_old_schema(monkeypatch):
    """When DB has old schema (shoes without user_id), lifespan migrates it."""
    monkeypatch.setenv("MIGRATION_PASSWORD", "migratepass")
    monkeypatch.delenv("SEED_DATA", raising=False)

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

    monkeypatch.setattr("backend.main.engine", engine)
    monkeypatch.setattr("backend.main.SessionLocal", sessionmaker(bind=engine))

    from backend.main import lifespan
    app = FastAPI()
    async_gen = lifespan(app)
    asyncio.run(async_gen.__aenter__())

    try:
        with engine.connect() as conn:
            tables = [row[0] for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()]
            assert "users" in tables, "users table should be created during migration"

            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(shoes)")).fetchall()]
            assert "user_id" in cols, "user_id column should be added to shoes"

            user_id = conn.execute(text("SELECT user_id FROM shoes")).fetchone()[0]
            assert user_id is not None, "existing shoes should get user_id assigned"

            joy_id = conn.execute(text("SELECT id FROM users WHERE username='Joy'")).fetchone()[0]
            assert joy_id == user_id, "shoes' user_id should match Joy's id"
    finally:
        asyncio.run(async_gen.__aexit__(None, None, None))


def test_lifespan_skips_migration_when_new_schema(monkeypatch):
    """When DB is empty or has users table, lifespan should not run migration logic."""
    monkeypatch.delenv("SEED_DATA", raising=False)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Empty DB — no tables yet
    monkeypatch.setattr("backend.main.engine", engine)
    monkeypatch.setattr("backend.main.SessionLocal", sessionmaker(bind=engine))

    from backend.main import lifespan
    app = FastAPI()
    async_gen = lifespan(app)
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

            # Migration didn't run, so no Joy user should exist
            count = conn.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
            assert count == 0
    finally:
        asyncio.run(async_gen.__aexit__(None, None, None))
