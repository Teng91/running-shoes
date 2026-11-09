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


def test_export_filename_uses_the_application_timezone_not_the_server_zone(monkeypatch):
    """SPEC-047: a UTC server still names exports with Taipei wall-clock time."""
    from backend import exporting

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 31, 16, 30, 5, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(clock, "datetime", FrozenDatetime)
    assert exporting.export_filename("csv", "all") == "running_shoes_all_20260201_003005.csv"


def test_account_backup_filename_uses_the_application_timezone(db, user_with_token):
    """v4.7.2: a backup taken at 00:30 in Taipei (16:30 UTC) is named for the Taipei day."""
    from backend.services.exports import build_account_export

    user, _ = user_with_token
    _, filename = build_account_export(db, user, now=datetime(2026, 1, 31, 16, 30, 5, tzinfo=UTC))
    assert filename == "running_shoes_account_20260201_003005.json"


def test_frontend_export_fallback_names_use_the_local_calendar_day():
    from pathlib import Path

    source = Path("frontend/app-exports.js").read_text(encoding="utf-8")
    assert "toISOString" not in source
    assert source.count("localDateISO()") == 2
