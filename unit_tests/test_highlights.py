"""SPEC-040 run-log highlights, shoe suggestion, milestones, year review and distance mix."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.auth import create_access_token, get_password_hash
from backend.dependencies import get_db
from backend.main import app
from backend.models import Run, RunningGoal, Shoe, User
from backend.read_models.highlights import (
    home_summary,
    shoe_distance_mix,
    shoe_suggestion,
    year_review,
)


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _shoe(db, user_id, **values):
    shoe = Shoe(user_id=user_id, brand=values.pop("brand", "Mizuno"), model=values.pop("model", "Sky"),
                date=values.pop("date", "2026-01-01"), price=values.pop("price", 5000),
                mileage=values.pop("mileage", 0), expected_mileage=800, monthly_km=0, **values)
    db.add(shoe)
    db.flush()
    return shoe


def _runs(db, user_id, shoe_id, *rows):
    db.add_all(Run(user_id=user_id, shoe_id=shoe_id, date=day, km=km) for day, km in rows)
    db.commit()


def test_suggestion_prefers_the_longest_rested_pair_and_demotes_worn_out_shoes(db, user_with_token):
    user, _ = user_with_token
    fresh = _shoe(db, user.id, model="Fresh", mileage=50)
    rested = _shoe(db, user.id, model="Rested", mileage=200)
    worn = _shoe(db, user.id, model="Worn", mileage=780)
    unworn = _shoe(db, user.id, model="New")
    _shoe(db, user.id, model="Retired", is_retired=True)
    _runs(db, user.id, fresh.id, ("2026-05-09", 5))
    _runs(db, user.id, rested.id, ("2026-04-20", 8))
    _runs(db, user.id, worn.id, ("2026-01-01", 8))

    ranked = shoe_suggestion(db, user.id, date(2026, 5, 10))

    assert [row["shoe_id"] for row in ranked] == [unworn.id, rested.id, fresh.id]
    assert ranked[0]["days_since_last_run"] is None
    assert ranked[1] == {"shoe_id": rested.id, "days_since_last_run": 20, "remaining_km": 600.0,
                         "usage_percent": 25.0, "near_end": False}
    # Without fresher pairs the worn-out shoe is still offered, flagged as near its end.
    db.query(Shoe).filter(Shoe.id.in_([fresh.id, rested.id, unworn.id])).update({"is_retired": True})
    db.commit()
    assert shoe_suggestion(db, user.id, date(2026, 5, 10))[0]["near_end"] is True


def test_home_summary_only_carries_the_next_shoe_suggestion(db, user_with_token):
    user, _ = user_with_token
    shoe = _shoe(db, user.id, mileage=310)
    _runs(db, user.id, shoe.id, ("2026-05-04", 6), ("2026-05-10", 3))

    summary = home_summary(db, user.id, date(2026, 5, 10))

    # SPEC-042: the week, streak, goal, total and records tiles were removed from the run log.
    assert set(summary) == {"as_of", "suggestion"}
    assert [row["shoe_id"] for row in summary["suggestion"]] == [shoe.id]


def test_year_review_summarizes_a_past_year_and_compares_the_previous_one(db, user_with_token):
    user, _ = user_with_token
    db.add(RunningGoal(user_id=user.id, start_year=2025, monthly_km=10))
    daily = _shoe(db, user.id, model="Daily", date="2025-02-01", price=3000)
    race = _shoe(db, user.id, model="Race", date="2025-06-01", price=6000)
    _shoe(db, user.id, model="Gone", date="2025-07-01", price=9999, is_deleted=True)
    _runs(db, user.id, daily.id, ("2024-12-31", 50), ("2025-03-03", 5), ("2025-03-04", 7), ("2025-03-05", 5))
    _runs(db, user.id, race.id, ("2025-10-12", 42.2))

    review = year_review(db, user.id, 2025, date(2026, 5, 10))

    assert review["complete"] is True and review["has_runs"] is True
    assert (review["total_km"], review["run_count"], review["run_days"]) == (59.2, 4, 4)
    assert review["longest_streak_days"] == 3
    assert review["longest_run"] == {"date": "2025-10-12", "km": 42.2, "shoe_id": race.id}
    assert review["biggest_month"] == {"month": 10, "km": 42.2}
    assert review["top_shoe"] == {"shoe_id": race.id, "km": 42.2, "runs": 1}
    assert (review["shoes_bought"], review["shoe_spend"]) == (2, 9000)
    assert review["cost_per_km"] == 152.03
    assert review["previous_year_km"] == 50
    assert review["goal"] == {"active": True, "yearly_km": 120, "percent": 49.3}
    assert year_review(db, user.id, 2027, date(2026, 5, 10)) == {
        "year": 2027, "end_date": None, "complete": False, "has_runs": False}
    current = year_review(db, user.id, 2026, date(2026, 5, 10))
    assert current["end_date"] == "2026-05-10" and current["has_runs"] is False


def test_distance_mix_buckets_runs_for_active_shoes_only(db, user_with_token):
    user, _ = user_with_token
    long_pair = _shoe(db, user.id, model="Long")
    easy_pair = _shoe(db, user.id, model="Easy")
    retired = _shoe(db, user.id, model="Old", is_retired=True)
    _runs(db, user.id, long_pair.id, ("2026-01-01", 4.99), ("2026-01-02", 19.99), ("2026-01-03", 20), ("2026-01-04", 30))
    _runs(db, user.id, easy_pair.id, ("2026-01-05", 5), ("2026-01-06", 9.9))
    _runs(db, user.id, retired.id, ("2026-01-07", 12))

    mix = shoe_distance_mix(db, user.id)

    # SPEC-042: 5 km steps, 20 km and longer share the last bucket.
    assert mix["buckets"] == ["<5", "5–10", "10–15", "15–20", "≥20"]
    assert [row["shoe_id"] for row in mix["shoes"]] == [long_pair.id, easy_pair.id]
    assert mix["shoes"][0] == {"shoe_id": long_pair.id, "counts": [1, 0, 0, 1, 2], "runs": 4,
                               "km": 74.98, "longest_km": 30, "average_km": 18.74}
    assert mix["shoes"][1]["counts"] == [0, 2, 0, 0, 0]


def test_highlight_endpoints_are_user_scoped(client, db, user_with_token):
    user, token = user_with_token
    other = User(username="other", hashed_password=get_password_hash("pass1234"))
    db.add(other)
    db.commit()
    mine, theirs = _shoe(db, user.id), _shoe(db, other.id)
    _runs(db, user.id, mine.id, ("2026-01-05", 5))
    _runs(db, other.id, theirs.id, ("2026-01-06", 42))
    headers = {"Authorization": f"Bearer {token}"}

    home = client.get("/api/analytics/home", headers=headers).json()
    review = client.get("/api/analytics/year-review?year=2026", headers=headers).json()
    mix = client.get("/api/analytics/shoe-distance-mix", headers=headers).json()

    assert [row["shoe_id"] for row in home["suggestion"]] == [mine.id]
    assert review["total_km"] == 5
    assert [row["shoe_id"] for row in mix["shoes"]] == [mine.id]
    other_headers = {"Authorization": f"Bearer {create_access_token(data={'sub': 'other'})}"}
    assert [row["shoe_id"] for row in client.get("/api/analytics/home", headers=other_headers).json()["suggestion"]] == [theirs.id]
    for path in ("/api/analytics/home", "/api/analytics/year-review?year=2026", "/api/analytics/shoe-distance-mix"):
        assert client.get(path).status_code == 401
    assert client.get("/api/analytics/year-review?year=1800", headers=headers).status_code == 422
