from datetime import UTC, date, datetime, timedelta

from backend import clock
from backend.read_models.rounding import round_metric


def test_app_timezone_is_fixed_utc_plus_eight():
    assert clock.APP_TIMEZONE.utcoffset(None) == timedelta(hours=8)


def test_local_today_rolls_over_at_taipei_midnight(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # 16:30 UTC is already 00:30 the next day in Taipei.
            return datetime(2026, 1, 31, 16, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(clock, "datetime", FrozenDatetime)
    assert clock.local_today() == date(2026, 2, 1)


def test_round_metric_treats_missing_aggregates_as_zero():
    assert round_metric(None) == 0.0
    assert round_metric(12.346) == 12.35
    assert round_metric(66.666, 1) == 66.7
