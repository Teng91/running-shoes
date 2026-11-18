"""SPEC-064 / SPEC-065: pace trend read model and weekday pace."""

from datetime import date

from backend.models import RaceGoal, Run, Shoe, User
from backend.read_models.pace import pace_analysis
from unit_tests.test_run_pace import client, headers

__all__ = ["client"]


def _owner(db, name):
    user = User(username=name, hashed_password="synthetic")
    db.add(user)
    db.flush()
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Sky", date="2025-01-01")
    db.add(shoe)
    db.flush()
    return user, shoe


def _runs(db, user, shoe, *rows):
    db.add_all(Run(user_id=user.id, shoe_id=shoe.id, date=day, km=km, duration_seconds=seconds)
               for day, km, seconds in rows)
    db.commit()


def test_pace_analysis_is_time_weighted_user_scoped_and_ignores_the_future(db, client):
    user, shoe = _owner(db, "pace-a")
    other, other_shoe = _owner(db, "pace-b")
    _runs(db, user, shoe,
          ("2026-01-05", 10, 3000), ("2026-01-06", 5, 1800), ("2026-01-07", 5, None),
          ("2026-03-10", 20, 7200), ("2026-12-01", 10, 2000))
    _runs(db, other, other_shoe, ("2026-01-05", 10, 6000))

    result = pace_analysis(db, user.id, date(2026, 6, 1))
    assert (result["timed_run_count"], result["untimed_run_count"]) == (3, 1)
    assert result["summary"] == {"first_date": "2026-01-05", "first_90_days_pace": 343,
                                 "recent_90_days_pace": 360, "recent_30_days_pace": None}
    assert [run["pace"] for run in result["runs"]] == [300, 360, 360]
    assert all(run["zone"] is None for run in result["runs"]), "zones need a race goal"
    assert (result["goal_pace"], result["zones"]) == (None, [])
    assert result["rolling"] == [{"date": "2026-01-05", "pace": 300}, {"date": "2026-01-06", "pace": 320},
                                 {"date": "2026-03-10", "pace": 360}]

    response = client.get("/api/analytics/pace", headers=headers(user))
    assert response.status_code == 200
    assert response.json()["timed_run_count"] == 3, "another account and future runs never count"
    assert client.get("/api/analytics/pace").status_code == 401


def test_pace_trend_points_carry_their_zone_once_a_race_goal_exists(db):
    user, shoe = _owner(db, "pace-zones")
    # Goal 2:00:00 for 20 km is 6:00/km: 6:50 is easy, 6:20 steady, 6:00 race pace, 5:40 fast.
    db.add(RaceGoal(user_id=user.id, version=1, race_date="2026-12-13", distance_km=20, target_seconds=7200))
    _runs(db, user, shoe, ("2026-11-01", 10, 4100), ("2026-11-02", 10, 3800), ("2026-11-03", 10, 3600),
          ("2026-11-04", 10, 3400))
    result = pace_analysis(db, user.id, date(2026, 11, 17))
    assert result["goal_pace"] == 360
    assert [run["zone"] for run in result["runs"]] == ["easy", "steady", "race", "fast"]
    assert [zone["key"] for zone in result["zones"]] == ["easy", "steady", "race", "fast"]


def test_pace_analysis_without_times_is_empty(db):
    user, shoe = _owner(db, "pace-empty")
    _runs(db, user, shoe, ("2026-01-05", 10, None))
    result = pace_analysis(db, user.id, date(2026, 6, 1))
    assert (result["timed_run_count"], result["untimed_run_count"], result["summary"]) == (0, 1, None)
    assert result["runs"] == result["rolling"] == []


def test_weekday_mix_reports_a_time_weighted_pace_per_weekday(db):
    from backend.read_models.trends import training_trends

    user, shoe = _owner(db, "pace-weekday")
    # Monday: 10 km at 5:00 and 5 km at 6:00 -> 4800 s / 15 km = 5:20; an untimed Monday run
    # adds distance but not pace. Saturday is untimed only; another account never counts.
    _runs(db, user, shoe, ("2026-10-05", 10, 3000), ("2026-10-12", 5, 1800), ("2026-10-12", 3, None),
          ("2026-10-10", 21.1, None))
    other, other_shoe = _owner(db, "pace-weekday-other")
    _runs(db, other, other_shoe, ("2026-10-05", 10, 6000))
    weekday = training_trends(db, user.id, 2026, date(2026, 10, 14))["weekday"]
    assert weekday[0] == {"weekday": 0, "km": 18, "run_days": 2, "runs": 3, "pace": 320}
    assert weekday[5]["pace"] is None and weekday[5]["km"] == 21.1
