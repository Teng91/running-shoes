"""SPEC-017: behavioral invariants, ambiguity and bounded query budgets."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend import goals, models
from backend.dependencies import get_db
from backend.main import app
from backend.tools import db_tools


@pytest.fixture
def stats_client(db, user_with_token):
    def session():
        yield db

    app.dependency_overrides[get_db] = session
    try:
        with TestClient(app) as client:
            yield client, {"Authorization": f"Bearer {user_with_token[1]}"}
    finally:
        app.dependency_overrides.clear()


def test_goal_progress_api_excludes_manual_adjustment(db, user_with_token, stats_client):
    user, _ = user_with_token
    shoe = models.Shoe(user_id=user.id, brand="A", model="Goal", date="2026-01-01")
    db.add(shoe)
    db.flush()
    db.add_all(
        [
            models.Run(user_id=user.id, shoe_id=shoe.id, date="2026-01-05", km=50),
            models.MonthlyMileage(user_id=user.id, year=2026, month=1, km=150, adjustment_km=100),
        ]
    )
    db.commit()
    client, headers = stats_client
    response = client.get("/api/running-goal/progress?year=2026&month=1", headers=headers)
    assert response.status_code == 200
    assert response.json()["month_km"] == 50
    assert response.json()["month_achievement_percent"] == 40
    assert response.json()["ytd_km"] == 50
    assert response.json() == goals.goal_progress(db, user.id, 2026, 1)
    assert (
        client.get("/api/running-goal/progress?year=2026&month=13", headers=headers).status_code
        == 422
    )


def test_spending_read_model_uses_calendar_months_and_user_scope(db, user_with_token):
    from backend.read_models.spending import spending_summary

    user, _ = user_with_token
    other = models.User(username="spending-other", hashed_password="synthetic")
    db.add(other)
    db.flush()
    db.add_all(
        [
            models.Shoe(
                user_id=user.id,
                brand="A",
                model="One",
                date="2026-03-01",
                price=800,
                orig_price=1000,
            ),
            models.Shoe(
                user_id=user.id,
                brand="A",
                model="Hidden",
                date="2025-01-01",
                price=9999,
                is_deleted=True,
            ),
            models.Shoe(
                user_id=other.id, brand="B", model="Private", date="2020-01-01", price=9999
            ),
        ]
    )
    db.commit()
    result = spending_summary(db, user.id, today=date(2026, 10, 20))
    assert result["start_month"] == "2026-03"
    assert result["month_span"] == 8
    assert result["average_monthly_paid"] == 100
    assert result["total_paid"] == 800
    assert result["savings"] == 200
    assert result["average_discount_percent"] == 80
    assert result["highest_month"] == {"year": 2026, "month": 3, "total_paid": 800}


def test_spending_summary_api_and_empty_history(stats_client):
    client, headers = stats_client
    result = client.get("/api/spending/summary", headers=headers)
    assert result.status_code == 200
    assert result.json()["month_span"] == 0
    assert result.json()["start_month"] is None
    assert result.json()["monthly"] == []


def test_tools_require_disambiguation_and_accept_owned_ids(db, user_with_token):
    user, _ = user_with_token
    other = models.User(username="matching-other", hashed_password="synthetic")
    db.add(other)
    db.flush()
    shoes = [
        models.Shoe(
            user_id=user.id,
            brand="A",
            model="Same",
            date="2025-01-01",
            mileage=700,
            is_retired=True,
        ),
        models.Shoe(user_id=user.id, brand="A", model="Same", date="2026-01-01", mileage=20),
        models.Shoe(user_id=other.id, brand="A", model="Private", date="2026-01-01"),
        models.Shoe(user_id=user.id, brand="A", model="Gone", date="2026-01-01", is_deleted=True),
    ]
    db.add_all(shoes)
    db.commit()
    for function in (db_tools.shoe_category_status, db_tools.shoe_usage_analytics):
        result = json.loads(function(db, user.id, shoe_name="A Same"))
        assert result["ok"] is False
        assert result["error"] == "ambiguous_shoe"
        assert {row["shoe_id"] for row in result["candidates"]} == {shoes[0].id, shoes[1].id}
        selected = json.loads(function(db, user.id, shoe_id=shoes[1].id))
        assert selected["ok"] is True
        for forbidden in shoes[2:]:
            assert (
                json.loads(function(db, user.id, shoe_id=forbidden.id))["error"] == "shoe_not_found"
            )
    compared = json.loads(
        db_tools.compare_shoes(db, user.id, shoe_a_id=shoes[0].id, shoe_b_id=shoes[1].id)
    )
    assert compared["ok"] is True
    assert compared["shoe_a"]["shoe_id"] != compared["shoe_b"]["shoe_id"]
    assert (
        json.loads(db_tools.compare_shoes(db, user.id, "Same", "Same"))["error"] == "ambiguous_shoe"
    )


@pytest.mark.parametrize("shoe_count", [0, 1, 12])
def test_shoe_usage_batch_has_constant_query_budget(db, user_with_token, shoe_count):
    user, _ = user_with_token
    uid = user.id
    shoes = [
        models.Shoe(user_id=uid, brand="A", model=str(i), date="2026-01-01")
        for i in range(shoe_count)
    ]
    db.add_all(shoes)
    db.flush()
    if shoes:
        db.add(models.Run(user_id=uid, shoe_id=shoes[0].id, date="2026-01-05", km=7))
    db.commit()
    queries = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        result = json.loads(db_tools.shoe_usage_analytics(db, uid))
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert result["shoe_count"] == shoe_count
    assert sum(row["logged_mileage_km"] for row in result["shoes"]) == (7 if shoes else 0)
    assert len(queries) <= 3, f"N+1 regression: {len(queries)} SELECTs"


def test_strava_parser_errors_are_framework_independent():
    from backend.strava_import import InvalidCSVError, parse_csv

    with pytest.raises(InvalidCSVError):
        parse_csv(b"invalid,headers\n1,2", max_rows=10)


def test_run_summary_is_complete_across_detail_pages_and_deleted_shoes(
    db, user_with_token, stats_client
):
    user, _ = user_with_token
    uid = user.id
    shoe = models.Shoe(
        user_id=uid, brand="A", model="Historical", date="2026-01-01", is_deleted=True
    )
    other = models.User(username="calendar-private", hashed_password="synthetic")
    db.add_all([shoe, other])
    db.flush()
    foreign_shoe = models.Shoe(user_id=other.id, brand="B", model="Private", date="2026-01-01")
    db.add(foreign_shoe)
    db.flush()
    db.add_all(
        [models.Run(user_id=uid, shoe_id=shoe.id, date="2026-01-05", km=1) for _ in range(205)]
    )
    db.add(models.Run(user_id=other.id, shoe_id=foreign_shoe.id, date="2026-01-05", km=999))
    db.commit()
    client, headers = stats_client
    summary = client.get("/api/runs/summary?year=2026&month=1", headers=headers).json()
    assert summary["total_km"] == 205
    assert summary["run_count"] == 205
    assert summary["run_days"] == 1
    assert summary["calendar"][0]["shoes"][0]["shoe_id"] == shoe.id
    rows = client.get("/api/runs?year=2026&month=1&offset=200&limit=201", headers=headers).json()
    assert len(rows) == 5
    assert client.get("/api/runs?year=2026&month=1&day=6", headers=headers).json() == []
    assert client.get("/api/runs?day=1", headers=headers).status_code == 422
    assert client.get("/api/runs?year=2026&month=2&day=31", headers=headers).status_code == 422


def test_shoe_metrics_agree_across_list_analysis_tools_and_export(
    db, user_with_token, stats_client
):
    from backend.exporting import generate_shoe_rows

    user, _ = user_with_token
    shoe = models.Shoe(
        user_id=user.id,
        brand="A",
        model="Metrics",
        date="2026-01-01",
        price=2400,
        orig_price=4000,
        mileage=100,
        expected_mileage=800,
    )
    db.add(shoe)
    db.commit()
    client, headers = stats_client
    listed = client.get("/api/shoes/active", headers=headers).json()[0]
    analysis = client.get(f"/api/shoes/{shoe.id}/analytics", headers=headers).json()
    tool = json.loads(db_tools.compare_shoes(db, user.id, shoe_a_id=shoe.id))
    assert tool["ok"] is False  # Missing second selection never guesses.
    exported = next(generate_shoe_rows([shoe]))
    assert listed["discount_percent"] == exported["折數(%)"] == 60
    assert listed["cost_per_km"] == analysis["usage"]["cost_per_km"] == exported["每km成本"] == 24
    assert (
        listed["usage_percent"]
        == analysis["lifecycle"]["usage_percent"]
        == exported["生命進度(%)"]
        == 12.5
    )
