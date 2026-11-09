
import pytest
from fastapi.testclient import TestClient

from backend.auth import get_password_hash
from backend.dependencies import get_db
from backend.main import app
from backend.models import MonthlyMileage, Shoe, User


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
    assert "8 characters" in res.json()["detail"]


@pytest.mark.parametrize("password", ["a" * 73, "密" * 25])
def test_auth_rejects_passwords_over_bcrypt_byte_limit(client, password):
    register = client.post(
        "/api/auth/register", json={"username": "alice", "password": password}
    )
    login = client.post(
        "/api/auth/login", json={"username": "alice", "password": password}
    )
    change = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "pass1234", "new_password": password,
    })
    assert register.status_code == 422
    assert login.status_code == 422
    assert change.status_code == 422


def test_register_duplicate_username(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("pass1234")))
    db.commit()
    res = client.post("/api/auth/register", json={"username": "alice", "password": "pass1234"})
    assert res.status_code == 400


def test_register_strips_whitespace(client):
    res = client.post("/api/auth/register", json={"username": "  alice  ", "password": "pass1234"})
    assert res.status_code == 200
    assert res.json()["username"] == "alice"
    # Logging in with the stripped name works
    login = client.post("/api/auth/login", json={"username": "alice", "password": "pass1234"})
    assert login.status_code == 200


def test_register_whitespace_only_rejected(client):
    res = client.post("/api/auth/register", json={"username": "   ", "password": "pass1234"})
    assert res.status_code == 400


def test_register_overlong_username_rejected(client):
    res = client.post("/api/auth/register", json={"username": "x" * 51, "password": "pass1234"})
    assert res.status_code == 422


def test_login_success(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("pass1234")))
    db.commit()
    res = client.post("/api/auth/login", json={"username": "alice", "password": "pass1234"})
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_login_user_not_found(client):
    res = client.post("/api/auth/login", json={"username": "nobody", "password": "pass1234"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect username or password"


def test_login_wrong_password(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("pass1234")))
    db.commit()
    res = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect username or password"


def test_change_password(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass1")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "oldpass1", "new_password": "newpass1",
    })
    assert res.status_code == 200
    # Verify new password works
    res = client.post("/api/auth/login", json={"username": "alice", "password": "newpass1"})
    assert res.status_code == 200


def test_change_password_user_not_found(client):
    res = client.post("/api/auth/change-password", json={
        "username": "nobody", "old_password": "oldpass1", "new_password": "newpass1",
    })
    assert res.status_code == 401


def test_change_password_wrong_old(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass1")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "wrong", "new_password": "newpass1",
    })
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect username or old password"


def test_change_password_short_new(client, db):
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass1")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "oldpass1", "new_password": "ab",
    })
    assert res.status_code == 400


def test_change_password_empty_old(client, db):
    """Empty old_password should be treated as wrong password (401), not crash."""
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass1")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "", "new_password": "newpass1",
    })
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect username or old password"


def test_change_password_empty_new(client, db):
    """Empty new_password should fail the length check (400)."""
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass1")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "oldpass1", "new_password": "",
    })
    assert res.status_code == 400
    assert "8 characters" in res.json()["detail"]


def test_change_password_same_as_old(client, db):
    """Changing to the same password is allowed (no-op effectively)."""
    db.add(User(username="alice", hashed_password=get_password_hash("oldpass1")))
    db.commit()
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "oldpass1", "new_password": "oldpass1",
    })
    assert res.status_code == 200


def test_change_password_chained(client, db):
    """After changing password, the new password works as old_password for subsequent changes."""
    db.add(User(username="alice", hashed_password=get_password_hash("password1")))
    db.commit()
    # First change
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "password1", "new_password": "password2",
    })
    assert res.status_code == 200
    # Second change must use pass2 as old_password
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "password1", "new_password": "password3",
    })
    assert res.status_code == 401  # pass1 no longer valid
    res = client.post("/api/auth/change-password", json={
        "username": "alice", "old_password": "password2", "new_password": "password3",
    })
    assert res.status_code == 200


def test_get_me_authenticated(client, user_with_token):
    """GET /api/auth/me returns the current user's info."""
    _user, token = user_with_token
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
    _user, token = user_with_token
    res = client.get("/api/shoes/active", headers=_auth_header(token))
    assert res.status_code == 200
    assert res.json() == []


def test_create_shoe(client, db, user_with_token):
    user, token = user_with_token
    res = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "Mizuno", "model": "Wave Sky 7", "date": "2024-01-01",
        "price": 2390, "orig_price": 4780, "mileage": 100,
        "expected_mileage": 800, "monthly_km": 60,
        "categories": ["Daily"],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["brand"] == "Mizuno"
    assert data["user_id"] == user.id
    assert data["categories"] == ["Daily"]


def test_create_shoe_rejects_blank_or_oversized_text(client, user_with_token):
    _, token = user_with_token
    blank = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "   ", "model": "Model", "date": "2026-01-01",
    })
    oversized = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "B", "model": "x" * 101, "date": "2026-01-01",
    })
    duplicate_categories = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "B", "model": "M", "date": "2026-01-01",
        "categories": ["Daily", "Daily"],
    })
    assert blank.status_code == 422
    assert oversized.status_code == 422
    assert duplicate_categories.status_code == 422


def test_create_shoe_rejects_invalid_category(client, user_with_token):
    _user, token = user_with_token
    res = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "Mizuno", "model": "Wave Sky 7", "date": "2024-01-01",
        "categories": ["Walking"],
    })
    assert res.status_code == 422


def test_update_shoe_categories(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01")
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    res = client.put(f"/api/shoes/{shoe.id}", headers=_auth_header(token), json={
        "categories": ["Tempo"],
    })
    assert res.status_code == 200
    assert res.json()["categories"] == ["Tempo"]


def test_create_shoe_rejects_trail_category(client, user_with_token):
    _user, token = user_with_token
    res = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "Salomon", "model": "Sense Ride", "date": "2026-01-01",
        "categories": ["Trail"],
    })
    assert res.status_code == 422


def test_create_shoe_rejects_walk_category(client, user_with_token):
    """Discontinued categories cannot be added through the API."""
    _user, token = user_with_token
    res = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "Nike", "model": "Free RN", "date": "2026-01-01",
        "categories": ["Walk"],
    })
    assert res.status_code == 422


def test_update_shoe_rejects_walk_but_allows_unclassified(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Test", model="Retired", date="2026-01-01",
                is_retired=True, categories=["Daily"])
    db.add(shoe)
    db.commit()
    response = client.put(f"/api/shoes/{shoe.id}", headers=_auth_header(token), json={
        "categories": ["Walk"],
    })
    assert response.status_code == 422
    response = client.put(f"/api/shoes/{shoe.id}", headers=_auth_header(token), json={
        "categories": [],
    })
    assert response.status_code == 200
    assert response.json()["categories"] == []


def test_create_shoe_with_multiple_categories(client, user_with_token):
    _user, token = user_with_token
    res = client.post("/api/shoes", headers=_auth_header(token), json={
        "brand": "Brooks", "model": "Ghost", "date": "2026-01-01",
        "categories": ["Daily", "Tempo"],
    })
    assert res.status_code == 200
    assert res.json()["categories"] == ["Daily", "Tempo"]


def test_update_shoe_adds_categories(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01",
                categories=["Daily"])
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    res = client.put(f"/api/shoes/{shoe.id}", headers=_auth_header(token), json={
        "categories": ["Daily", "Tempo"],
    })
    assert res.status_code == 200
    assert res.json()["categories"] == ["Daily", "Tempo"]


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


def test_stale_shoe_delete_is_rejected(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    stale_version = shoe.version
    updated = client.put(
        f"/api/shoes/{shoe.id}",
        headers=_auth_header(token),
        json={"price": 100, "expected_version": stale_version},
    )

    deleted = client.delete(
        f"/api/shoes/{shoe.id}?expected_version={stale_version}",
        headers=_auth_header(token),
    )

    assert updated.status_code == 200
    assert deleted.status_code == 409
    assert client.get("/api/shoes/active", headers=_auth_header(token)).json()[0][
        "price"
    ] == 100


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
    _user, token = user_with_token
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
    _user, token = user_with_token
    res = client.post("/api/monthly-mileage", headers=_auth_header(token), json={
        "year": 2026, "month": 13, "km": 10,
    })
    assert res.status_code == 422


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
    res = client.put(f"/api/monthly-mileage/{entry.id}", headers=_auth_header(token), json={
        "km": 75.5, "expected_version": entry.version,
    })
    assert res.status_code == 200
    assert res.json()["km"] == 75.5
    assert res.json()["version"] == 1
    stale = client.put(f"/api/monthly-mileage/{entry.id}", headers=_auth_header(token), json={
        "km": 90, "expected_version": 0,
    })
    stale_delete = client.delete(
        f"/api/monthly-mileage/{entry.id}?expected_version=0",
        headers=_auth_header(token),
    )
    assert stale.status_code == 409
    assert stale_delete.status_code == 409
    assert client.get("/api/monthly-mileage", headers=_auth_header(token)).json()[0][
        "km"
    ] == 75.5


def test_update_monthly_mileage_not_found(client, user_with_token):
    _user, token = user_with_token
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


@pytest.mark.parametrize(("password", "status"), [("1234567", 400), ("12345678", 200)])
def test_register_requires_eight_character_passwords(client, password, status):
    res = client.post("/api/auth/register", json={"username": "boundary", "password": password})
    assert res.status_code == status
