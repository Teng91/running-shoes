"""SPEC-064: pace analytics read model and API."""

import statistics
from datetime import date, timedelta

from backend.models import Run, Shoe, User
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
    assert result["rolling"] == [{"date": "2026-01-05", "pace": 300}, {"date": "2026-01-06", "pace": 320},
                                 {"date": "2026-03-10", "pace": 360}]
    assert result["monthly"] == [
        {"month": "2026-01", "km": 20.0, "timed_km": 15.0, "runs": 3, "pace": 320},
        {"month": "2026-02", "km": 0.0, "timed_km": 0.0, "runs": 0, "pace": None},
        {"month": "2026-03", "km": 20.0, "timed_km": 20.0, "runs": 1, "pace": 360},
    ]
    assert result["monthly_lag"]["prior_months_correlation"] is None
    bands = {band["min_km"]: band for band in result["distance"]}
    assert (bands[5]["runs"], bands[5]["pace"]) == (1, 360)
    assert (bands[8]["pace"], bands[8]["fastest_pace"]) == (300, 300)
    assert (bands[16]["pace"], bands[0]["runs"], bands[22]["max_km"]) == (360, 0, None)
    distribution = result["distribution"]
    assert distribution["median_pace"] == 360
    assert [(item["min_pace"], item["runs"]) for item in distribution["bins"]] == [
        (300, 1), (315, 0), (330, 0), (345, 0), (360, 2)]
    assert distribution["bins"][0]["open_min"] and distribution["bins"][-1]["open_max"]

    response = client.get("/api/analytics/pace", headers=headers(user))
    assert response.status_code == 200
    assert response.json()["timed_run_count"] == 3, "another account and future runs never count"
    assert client.get("/api/analytics/pace").status_code == 401


def test_training_load_relates_prior_weeks_to_pace(db):
    user, shoe = _owner(db, "pace-load")
    start = date(2026, 1, 5)  # a Monday
    rows = []
    for week in range(16):
        km = 12 if week < 8 else 32
        pace = 380 if week < 10 else 350
        rows.append(((start + timedelta(weeks=week)).isoformat(), km, km * pace))
    _runs(db, user, shoe, *rows)

    load = pace_analysis(db, user.id, start + timedelta(weeks=15, days=1))["load"]
    xs = [12, 12, 12, 12, 12, 17, 22, 27, 32, 32, 32, 32]
    ys = [380] * 6 + [350] * 6
    assert [point["prior_week_km"] for point in load["points"]] == xs
    assert [point["pace"] for point in load["points"]] == ys
    assert load["correlation"] == round(statistics.correlation(xs, ys), 2) < 0
    slope, intercept = statistics.linear_regression(xs, ys)
    assert load["trend"] == {"slope_seconds_per_10km": round(slope * 10, 1), "intercept": round(intercept, 1),
                             "min_km": 12, "max_km": 32}
    # 20–30 km has only two weeks, fewer than the three a bucket needs.
    assert [(bucket["min_km"], bucket["weeks"], bucket["median_pace"]) for bucket in load["buckets"]] == [
        (10, 6, 380), (30, 4, 350)]
    assert load["comparison"]["seconds_faster"] == 30


def test_pace_analysis_without_times_is_empty(db):
    user, shoe = _owner(db, "pace-empty")
    _runs(db, user, shoe, ("2026-01-05", 10, None))
    result = pace_analysis(db, user.id, date(2026, 6, 1))
    assert (result["timed_run_count"], result["untimed_run_count"], result["summary"]) == (0, 1, None)
    assert result["runs"] == result["monthly"] == result["distance"] == []
    assert result["load"]["points"] == [] and result["load"]["comparison"] is None
    assert result["distribution"]["bins"] == []


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
