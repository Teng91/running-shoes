from datetime import date

import pytest
from sqlalchemy import event

from backend import analytics, forecasting, models
from backend.routers.shoes import list_active, list_retired


@pytest.mark.parametrize(("mileage", "expected", "planned", "recent", "source", "has_date"), [
    (300, 900, 60, 300, "recent_90_days", True),
    (300, 900, 60, 0, "planned_monthly_km", True),
    (300, 900, 0, 0, "planned_monthly_km", False),
    (900, 900, 60, 300, "recent_90_days", False),
    (300, 900, 60, 0.0001, "planned_monthly_km", True),
    (0, 1e20, 0.01, 0, "planned_monthly_km", False),
])
def test_retirement_forecast_policy(mileage, expected, planned, recent, source, has_date):
    shoe = models.Shoe(mileage=mileage, expected_mileage=expected, monthly_km=planned)
    result = forecasting.retirement_forecast(shoe, recent, date(2026, 10, 19))
    assert result["forecast_source"] == source
    assert (result["forecast_retirement_date"] is not None) == has_date
    if recent == 300 and mileage == 300:
        assert result["forecast_retirement_date"] == "2027-04-17"
    assert result["remaining_mileage_km"] >= 0


def test_a_pair_idle_for_90_days_gets_no_forecast_but_a_new_pair_uses_the_plan(db, user_with_token):
    """SPEC-069: occasional shoes (hiking, racing) have no usable rate; never-worn pairs use the plan."""
    shoe = models.Shoe(mileage=20.9, expected_mileage=600, monthly_km=60)
    idle = forecasting.retirement_forecast(shoe, 0, date(2026, 11, 18), has_runs=True)
    assert (idle["forecast_source"], idle["forecast_retirement_date"], idle["forecast_monthly_km"]) == ("idle_90_days", None, 0)
    assert idle["remaining_mileage_km"] == 579.1
    fresh = forecasting.retirement_forecast(shoe, 0, date(2026, 11, 18))
    assert fresh["forecast_source"] == "planned_monthly_km" and fresh["forecast_retirement_date"] is not None

    user, _ = user_with_token
    hiking, new, daily = (models.Shoe(user_id=user.id, brand="NB", model=name, date="2026-01-24", mileage=20.9,
                                      expected_mileage=600, monthly_km=60) for name in ("Hierro", "New", "Daily"))
    db.add_all([hiking, new, daily])
    db.flush()
    db.add_all([models.Run(user_id=user.id, shoe_id=hiking.id, date="2026-08-02", km=5.04),
                models.Run(user_id=user.id, shoe_id=daily.id, date="2026-11-10", km=10),
                models.Run(user_id=user.id, shoe_id=new.id, date="2026-12-01", km=5)])  # future: not yet worn
    db.commit()
    as_of = date(2026, 11, 18)
    batch = forecasting.forecasts_for_shoes(db, user.id, [hiking, new, daily], today=as_of)
    assert [batch[shoe.id]["forecast_source"] for shoe in (hiking, new, daily)] == [
        "idle_90_days", "planned_monthly_km", "recent_90_days"]
    analysis = analytics.shoe_analytics(db, user.id, hiking.id, today=as_of)["lifecycle"]
    assert (analysis["forecast_source"], analysis["forecast_retirement_date"]) == ("idle_90_days", None)


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
        result = analytics.shoe_analytics(db, user.id, output.id, today=as_of)
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
    lifecycle = analytics.shoe_analytics(db, user.id, shoe.id, today=date(2026, 10, 19))["lifecycle"]
    assert (lifecycle["forecast_retirement_date"], lifecycle["forecast_source"]) == (None, "retired")
    assert lifecycle["remaining_mileage_km"] == 300
    tool = json.loads(db_tools.shoe_usage_analytics(db, user.id))["shoes"][0]
    assert (tool["forecast_retirement_date"], tool["forecast_source"]) == (None, "retired")
