"""SPEC-065: target race goal, prediction, intensity mix and long-run readiness."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import configure_sqlite_connection
from backend.migrations import run_startup_migrations, schema_version
from backend.models import RaceGoal, Run
from backend.read_models.race_readiness import predict_seconds, race_readiness, zone_for
from unit_tests.test_run_pace import client, headers, owner

__all__ = ["client"]

HALF = {"race_name": "示範半馬", "race_date": "2026-12-13", "distance_km": 21.0975, "target_seconds": 7200,
        "reference_distance_km": 10, "reference_seconds": 3120, "reference_temperature_c": 28}


def test_race_goal_is_saved_versioned_validated_and_user_scoped(client, db):
    user, _ = owner(db, "race-owner")
    other, _ = owner(db, "race-other")
    assert client.get("/api/race-goal", headers=headers(user)).json() is None

    saved = client.put("/api/race-goal", headers=headers(user), json={**HALF, "race_name": "  示範半馬 "})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {**HALF, "plan_weeks": None, "version": 1}
    stale = client.put("/api/race-goal", headers=headers(user), json={**HALF, "expected_version": 0})
    assert stale.status_code == 409
    updated = client.put("/api/race-goal", headers=headers(user), json={**HALF, "target_seconds": 7100, "expected_version": 1})
    assert updated.json()["version"] == 2 and updated.json()["target_seconds"] == 7100
    assert client.get("/api/race-goal", headers=headers(other)).json() is None, "another account sees nothing"

    for bad in ({"race_date": "2026-13-01"}, {"race_date": "2026/12/06"}, {"target_seconds": 30},
                {"target_seconds": 7200.5}, {"reference_seconds": None},
                {"reference_distance_km": None, "reference_seconds": None},
                {"reference_seconds": 60}, {"distance_km": 0.5}, {"reference_temperature_c": 70},
                {"plan_weeks": 3}, {"plan_weeks": 25}, {"plan_weeks": 8.5}, {"plan_weeks": "8"}):
        response = client.put("/api/race-goal", headers=headers(user), json={**HALF, **bad})
        assert response.status_code == 422, bad
    no_reference = {**HALF, "reference_distance_km": None, "reference_seconds": None, "reference_temperature_c": None}
    assert client.put("/api/race-goal", headers=headers(other), json=no_reference).status_code == 200

    assert client.delete("/api/race-goal?expected_version=1", headers=headers(user)).status_code == 409
    assert client.delete("/api/race-goal?expected_version=2", headers=headers(user)).status_code == 200
    assert client.get("/api/race-goal", headers=headers(user)).json() is None
    assert client.get("/api/race-goal", headers=headers(other)).json()["reference_seconds"] is None
    assert client.get("/api/race-goal").status_code == 401


def test_prediction_and_zones_follow_the_goal_race_pace():
    # Riegel: 52:00 for 10 km predicts 1:54:44 for a half marathon.
    assert predict_seconds(3120, 10, 21.0975) == 6884
    goal_pace = 7200 / 21.0975  # 5:41.3 per km
    assert [zone_for(goal_pace + offset, goal_pace) for offset in (60, 45, 44, 15, 14, -10, -11)] == [
        "easy", "easy", "steady", "steady", "race", "race", "fast"]


def test_readiness_reports_prediction_intensity_and_long_runs(client, db):
    user, shoe = owner(db, "race-ready")
    other, other_shoe = owner(db, "race-ready-other")
    as_of = date(2026, 11, 17)
    db.add(RaceGoal(user_id=user.id, version=1, **HALF))
    rows = [
        ("2026-10-25", 16, 5410),  # long run at 5:38: race pace, 76% of the distance
        ("2026-11-08", 10, 3900),     # 6:30: easy
        ("2026-11-10", 10, 3600),     # 6:00: steady
        ("2026-11-15", 13, 4350),  # 5:35: race pace
        ("2026-11-16", 5, None),      # untimed: counted as distance, not intensity
        ("2026-09-01", 18, 6800),     # older than eight weeks: not a recent long run
        ("2026-11-30", 20, 7000),     # future: ignored
    ]
    db.add_all(Run(user_id=user.id, shoe_id=shoe.id, date=day, km=km, duration_seconds=seconds) for day, km, seconds in rows)
    db.add(Run(user_id=other.id, shoe_id=other_shoe.id, date="2026-11-14", km=21, duration_seconds=7000))
    db.commit()

    result = race_readiness(db, user.id, as_of)
    assert (result["days_left"], result["goal_pace"]) == (26, 341)
    assert result["prediction"] == {
        "reference_distance_km": 10, "reference_seconds": 3120, "reference_pace": 312, "reference_temperature_c": 28,
        "hot_reference": True, "predicted_seconds": 6884, "predicted_pace": 326, "margin_seconds": 316}
    zones = {zone["key"]: zone for zone in result["intensity"]["zones"]}
    assert {key: zone["runs"] for key, zone in zones.items()} == {"easy": 1, "steady": 1, "race": 2, "fast": 0}
    assert result["intensity"]["untimed_runs"] == 1
    total = 5410 + 3900 + 3600 + 4350
    assert result["intensity"]["total_seconds"] == total
    assert zones["race"]["share"] == round((5410 + 4350) / total * 100, 1)
    assert sum(zone["share"] for zone in zones.values()) == pytest.approx(100, abs=0.2)

    long = result["long_runs"]
    assert (long["threshold_km"], long["count"], long["target_count"], long["enough"]) == (15.8, 1, 2, False)
    assert long["longest_recent"] == {"date": "2026-10-25", "km": 16, "pace": 338}
    assert long["longest_ever"]["km"] == 18, "the future 20 km run is ignored"
    assert long["longest_recent_percent"] == 76
    assert long["last_long_run_by"] == "2026-11-29"
    assert len(long["weekly"]) == 12 and long["weekly"][-1] == {
        "week_start": "2026-11-16", "km": 5, "longest_km": 5, "partial": True}
    assert long["average_weekly_km"] == round((16 + 10 + 10 + 13 + 5) / 8, 2)

    response = client.get("/api/analytics/race", headers=headers(user)).json()
    assert response["goal"]["target_seconds"] == 7200
    assert client.get("/api/analytics/race", headers=headers(other)).json()["goal"] is None
    assert client.get("/api/analytics/race").status_code == 401


def test_a_second_long_run_makes_the_build_enough():
    from unittest.mock import MagicMock

    from backend.read_models import race_readiness as module
    goal = {**HALF, "version": 1}
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        ("2026-10-25", 16, 5410), ("2026-11-08", 17, 6500)]
    original = module.race_goal_values
    module.race_goal_values = lambda *_: goal
    try:
        long = module.race_readiness(db, 1, date(2026, 11, 17))["long_runs"]
    finally:
        module.race_goal_values = original
    assert (long["count"], long["enough"]) == (2, True)


def test_schema_ten_rollback_keeps_the_race_goal_and_reupgrades(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback10.sqlite'}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    sessions = sessionmaker(bind=engine, autoflush=False)
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 14
    with sessions() as db:
        user, _ = owner(db, "rollback10")
        db.add(RaceGoal(user_id=user.id, version=1, **HALF))
        db.commit()
    script = Path("scripts/rollback_schema_ten.sql").read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        connection.executescript(Path("scripts/rollback_schema_fourteen.sql").read_text(encoding="utf-8"))
        connection.executescript(Path("scripts/rollback_schema_thirteen.sql").read_text(encoding="utf-8"))
        connection.executescript(Path("scripts/rollback_schema_twelve.sql").read_text(encoding="utf-8"))
        connection.executescript(Path("scripts/rollback_schema_eleven.sql").read_text(encoding="utf-8"))
        connection.executescript(script)
        with pytest.raises(Exception, match="CHECK constraint failed"):
            connection.executescript(script)
        connection.rollback()
    finally:
        connection.close()
    assert schema_version(engine) == 9
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 14
    with sessions() as db:
        assert db.query(RaceGoal).one().target_seconds == 7200
    engine.dispose()

