import pytest
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.models import User, Shoe, MonthlyMileage
from backend.auth import get_password_hash
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


def test_reset_password(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass")))
    db.commit()
    res = client.post("/api/auth/reset-password", json={"username": "alice", "new_password": "newpass1"})
    assert res.status_code == 200
    # Verify new password works
    res = client.post("/api/auth/login", json={"username": "alice", "password": "newpass1"})
    assert res.status_code == 200


def test_reset_password_user_not_found(client):
    res = client.post("/api/auth/reset-password", json={"username": "nobody", "new_password": "newpass1"})
    assert res.status_code == 404


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


def test_unauthenticated_access(client):
    res = client.get("/api/shoes/active")
    assert res.status_code == 401  # No credentials provided


# ── Monthly Mileage CRUD Tests ────────────────────────────────

def test_list_monthly_mileage_empty(client, user_with_token):
    user, token = user_with_token
    res = client.get("/api/monthly-mileage", headers=_auth_header(token))
    assert res.status_code == 200
    assert res.json() == []


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
