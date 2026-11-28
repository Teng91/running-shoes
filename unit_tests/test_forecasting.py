from datetime import date, timedelta

import pytest
from sqlalchemy import event

from backend import forecasting, models
from backend.read_models import insights
from backend.routers.shoes import list_active, list_retired


@pytest.mark.parametrize(("mileage", "expected", "planned", "recent", "source", "has_date"), [
    (300, 900, 60, 300, "recent_90_days", True),
    (300, 900, 60, 0, "no_runs", False),
    (300, 900, 0, 0, "no_runs", False),
    (900, 900, 60, 300, "recent_90_days", False),
    (300, 900, 60, 0.0001, "no_runs", False),
    (0, 1e20, 0.01, 0.03, "recent_90_days", False),
])
def test_retirement_forecast_policy(mileage, expected, planned, recent, source, has_date):
    shoe = models.Shoe(mileage=mileage, expected_mileage=expected, monthly_km=planned)
    result = forecasting.retirement_forecast(shoe, recent, date(2026, 10, 19))
    assert result["forecast_source"] == source
    assert (result["forecast_retirement_date"] is not None) == has_date
    if recent == 300 and mileage == 300:
        assert result["forecast_retirement_date"] == "2027-04-17"
    assert result["remaining_mileage_km"] >= 0


def test_idle_and_never_worn_pairs_get_no_forecast(db, user_with_token):
    """SPEC-069/138: occasional shoes (hiking, racing) and never-worn pairs have no usable rate."""
    shoe = models.Shoe(mileage=20.9, expected_mileage=600, monthly_km=60)
    idle = forecasting.retirement_forecast(shoe, 0, date(2026, 11, 18), has_runs=True)
    assert (idle["forecast_source"], idle["forecast_retirement_date"], idle["forecast_monthly_km"]) == ("idle_90_days", None, 0)
    assert idle["remaining_mileage_km"] == 579.1
    fresh = forecasting.retirement_forecast(shoe, 0, date(2026, 11, 18))
    # SPEC-138: a pair never logged gets no date either; the planned monthly km is gone.
    assert fresh["forecast_source"] == "no_runs" and fresh["forecast_retirement_date"] is None

    user, _ = user_with_token
    hiking, new, daily = (models.Shoe(user_id=user.id, brand="NB", model=name, date="2026-01-24", mileage=20.9,
                                      expected_mileage=600, monthly_km=60) for name in ("Trail", "New", "Daily"))
    db.add_all([hiking, new, daily])
    db.flush()
    db.add_all([models.Run(user_id=user.id, shoe_id=hiking.id, date="2026-08-02", km=5.04),
                models.Run(user_id=user.id, shoe_id=daily.id, date="2026-11-10", km=10),
                models.Run(user_id=user.id, shoe_id=new.id, date="2026-12-01", km=5)])  # future: not yet worn
    db.commit()
    as_of = date(2026, 11, 18)
    batch = forecasting.forecasts_for_shoes(db, user.id, [hiking, new, daily], today=as_of)
    assert [batch[shoe.id]["forecast_source"] for shoe in (hiking, new, daily)] == [
        "idle_90_days", "no_runs", "recent_90_days"]
    analysis = insights.shoe_analytics(db, user.id, hiking.id, today=as_of)["lifecycle"]
    assert (analysis["forecast_source"], analysis["forecast_retirement_date"]) == ("idle_90_days", None)


@pytest.mark.parametrize(("first", "days"), [
    (None, 90), ("2026-01-01", 90), ("2026-08-21", 90), ("2026-08-22", 89),
    ("2026-10-30", 20), ("2026-11-10", 14), ("2026-11-18", 14), ("not-a-date", 90),
])
def test_rate_window_starts_at_the_first_run_inside_90_days(first, days):
    assert forecasting.rate_window_days(first, date(2026, 11, 18)) == days


def test_a_pair_first_worn_inside_the_window_is_averaged_over_its_days_in_use(db, user_with_token):
    """SPEC-142: 100 km in a new pair's first 20 days is ~152 km a month, not 100 km over 90 days."""
    user, _ = user_with_token
    new, single = (models.Shoe(user_id=user.id, brand="ASICS", model=name, date="2026-10-30",
                               mileage=100, expected_mileage=800) for name in ("Novablast", "Single"))
    db.add_all([new, single])
    db.flush()
    db.add_all([models.Run(user_id=user.id, shoe_id=new.id, date=(date(2026, 10, 30) + timedelta(days=day)).isoformat(),
                           km=5) for day in range(20)])
    # One long run yesterday is averaged over at least two weeks.
    db.add(models.Run(user_id=user.id, shoe_id=single.id, date="2026-11-17", km=21))
    db.commit()
    as_of = date(2026, 11, 18)
    batch = forecasting.forecasts_for_shoes(db, user.id, [new, single], today=as_of)
    rate = round(100 / 20 * 30.4375, 2)
    assert batch[new.id]["forecast_monthly_km"] == batch[new.id]["actual_monthly_km_90_days"] == rate == 152.19
    assert batch[new.id]["forecast_retirement_date"] == (as_of + timedelta(days=round(700 / rate * 30.4375))).isoformat()
    assert batch[single.id]["forecast_monthly_km"] == round(21 / 14 * 30.4375, 2)
    for shoe in (new, single):
        lifecycle = insights.shoe_analytics(db, user.id, shoe.id, today=as_of)["lifecycle"]
        assert (lifecycle["forecast_monthly_km"], lifecycle["forecast_retirement_date"]) == (
            batch[shoe.id]["forecast_monthly_km"], batch[shoe.id]["forecast_retirement_date"])


def test_batch_forecast_is_scoped_bounded_and_matches_analysis(db, user_with_token, monkeypatch):
    user, _ = user_with_token
    other = models.User(username="forecast-other", hashed_password="synthetic")
    db.add(other)
    db.flush()
    shoes = [models.Shoe(user_id=user.id, brand="Test", model=f"shoe-{i}", date="2026-01-01",
                         mileage=300, expected_mileage=900, monthly_km=60, is_retired=i == 1)
             for i in range(3)]
    foreign = models.Shoe(user_id=other.id, brand="Other", model="Private", date="2026-01-01")
    db.add_all([*shoes, foreign])
    db.flush()
    shoes[2].is_deleted = True
    db.add_all([
        models.Run(user_id=user.id, shoe_id=shoes[0].id, date="2026-10-01", km=300),
        models.Run(user_id=user.id, shoe_id=shoes[0].id, date="2026-01-01", km=100),
        models.Run(user_id=user.id, shoe_id=shoes[0].id, date="2026-10-20", km=100),
        # A malformed legacy row still must not cross account boundaries.
        models.Run(user_id=other.id, shoe_id=shoes[0].id, date="2026-10-01", km=100),
    ])
    db.commit()
    as_of = date(2026, 10, 19)
    monkeypatch.setattr(forecasting, "local_today", lambda: as_of)
    queries = []

    def count_query(*args):
        queries.append(args[2])

    engine = db.get_bind()
    # Load ORM attributes before counting just the batch aggregation.
    for shoe in [*shoes, foreign]:
        _ = shoe.id, shoe.user_id, shoe.is_deleted
    user_id = user.id
    event.listen(engine, "before_cursor_execute", count_query)
    try:
        batch = forecasting.forecasts_for_shoes(db, user_id, [*shoes, foreign], today=as_of)
    finally:
        event.remove(engine, "before_cursor_execute", count_query)
    assert len(queries) == 1
    assert set(batch) == {shoes[0].id, shoes[1].id}
    assert forecasting.forecasts_for_shoes(db, user.id, []) == {}
    active = list_active(user, db)
    retired = list_retired(user, db)
    for output in [*active, *retired]:
        result = insights.shoe_analytics(db, user.id, output.id, today=as_of)
        assert result is not None
        analysis = {**result["lifecycle"], **result["usage"]}
        for field in forecasting.SHOE_RESPONSE_FIELDS:
            assert getattr(output, field) == analysis[field] == batch[output.id][field]
    assert active[0].forecast_retirement_date == "2027-04-17"
    # SPEC-050: the shoe list carries the same 90-day monthly average as the analysis window.
    assert active[0].actual_monthly_km_90_days == round(300 / 90 * 30.4375, 2)
    assert retired[0].actual_monthly_km_90_days == 0
    # SPEC-055: a retired pair is never given a future retirement date.
    assert retired[0].forecast_source == "retired"
    assert retired[0].forecast_retirement_date is None


def test_retired_shoes_have_no_retirement_forecast_in_analysis_or_ai_tools(db, user_with_token):
    """SPEC-055: a retired pair never gets a future retirement date, whatever lifespan remains."""
    import json

    from backend.tools import db_tools

    user, _ = user_with_token
    shoe = models.Shoe(user_id=user.id, brand="Mizuno", model="Sky", date="2025-01-01", mileage=500,
                       expected_mileage=800, monthly_km=60, is_retired=True)
    db.add(shoe)
    db.flush()
    db.add(models.Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-01", km=30))
    db.commit()
    lifecycle = insights.shoe_analytics(db, user.id, shoe.id, today=date(2026, 10, 19))["lifecycle"]
    assert (lifecycle["forecast_retirement_date"], lifecycle["forecast_source"]) == (None, "retired")
    assert lifecycle["remaining_mileage_km"] == 300
    tool = json.loads(db_tools.shoe_usage_analytics(db, user.id))["shoes"][0]
    assert (tool["forecast_retirement_date"], tool["forecast_source"]) == (None, "retired")
