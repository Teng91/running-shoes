import pytest
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.main import app
from backend.routers.strava import _parse_strava_csv


@pytest.fixture
def api(db, user_with_token):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    _, token = user_with_token
    try:
        yield TestClient(app, headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.clear()


def test_password_change_revokes_existing_session(api):
    assert api.get("/api/auth/me").status_code == 200
    assert api.post("/api/auth/change-password", json={
        "username": "testuser", "old_password": "pass1234", "new_password": "changed123",
    }).status_code == 200
    assert api.get("/api/auth/me").status_code == 401
    login = api.post("/api/auth/login", json={
        "username": "testuser", "password": "changed123",
    })
    assert login.status_code == 200
    assert api.get("/api/auth/me", headers={
        "Authorization": "Bearer " + login.json()["access_token"],
    }).status_code == 200


def test_stale_shoe_edit_cannot_erase_run_mileage(api):
    shoe = api.post("/api/shoes", json={
        "brand": "Test", "model": "Shoe", "date": "2026-01-01",
    }).json()
    assert api.post("/api/runs", json={
        "shoe_id": shoe["id"], "date": "2026-09-01", "km": 10,
    }).status_code == 200
    stale = api.put(f"/api/shoes/{shoe['id']}", json={
        "price": 123, "mileage": 0, "expected_version": shoe["version"],
    })
    assert stale.status_code == 409
    current = api.get("/api/shoes/active").json()[0]
    assert current["mileage"] == 10
    assert current["price"] == 0
    assert api.put(f"/api/shoes/{shoe['id']}", json={
        "price": 123, "expected_version": current["version"],
    }).status_code == 200
    assert api.get("/api/shoes/active").json()[0]["mileage"] == 10


@pytest.mark.parametrize("date", ["1899-12-31", "2101-01-01"])
def test_run_dates_cannot_poison_monthly_response(api, date):
    shoe = api.post("/api/shoes", json={
        "brand": "Test", "model": "Shoe", "date": "2026-01-01",
    }).json()
    assert api.post("/api/runs", json={
        "shoe_id": shoe["id"], "date": date, "km": 10,
    }).status_code == 422
    assert api.get("/api/monthly-mileage").json() == []
    csv = ("Activity ID,Activity Date,Activity Type,Activity Gear,Distance\n"
           f"1,{date},Run,Test,1000\n")
    rows, invalid, _ = _parse_strava_csv(csv.encode())
    assert rows == []
    assert invalid == 1
