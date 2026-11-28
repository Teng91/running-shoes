from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backend import clock
from backend.read_models.rounding import round_metric


def _frozen_now(monkeypatch, instant: datetime) -> None:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(clock, "datetime", FrozenDatetime)


def test_default_zone_is_taipei_without_daylight_saving():
    assert clock.DEFAULT_ZONE.key == clock.DEFAULT_TIMEZONE == "Asia/Taipei"
    for month in (1, 7):
        assert datetime(2026, month, 1, tzinfo=clock.DEFAULT_ZONE).utcoffset() == timedelta(hours=8)


def test_local_today_rolls_over_at_taipei_midnight(monkeypatch):
    # 16:30 UTC is already 00:30 the next day in Taipei.
    _frozen_now(monkeypatch, datetime(2026, 1, 31, 16, 30, tzinfo=UTC))
    assert clock.local_today() == date(2026, 2, 1)


def test_each_account_counts_today_in_its_own_zone(monkeypatch):
    """SPEC-147 AC-2: the same instant is a different calendar day for accounts in other zones."""
    _frozen_now(monkeypatch, datetime(2026, 1, 31, 16, 30, tzinfo=UTC))
    taipei = SimpleNamespace(timezone="Asia/Taipei")
    honolulu = SimpleNamespace(timezone="Pacific/Honolulu")
    london = SimpleNamespace(timezone="Europe/London")
    assert clock.user_today(taipei) == date(2026, 2, 1)
    assert clock.user_today(honolulu) == date(2026, 1, 31)
    assert clock.user_today(london) == date(2026, 1, 31)
    # A row without a zone (old adapters, tests) keeps the default calendar.
    assert clock.user_today(SimpleNamespace()) == date(2026, 2, 1)


def test_daylight_saving_moves_the_day_boundary(monkeypatch):
    """SPEC-147 AC-3: offsets come from the zone rules for that instant, never a fixed number."""
    new_york = SimpleNamespace(timezone="America/New_York")
    # 04:30 UTC is 23:30 EST (UTC-5) in January but 00:30 EDT (UTC-4) in July.
    _frozen_now(monkeypatch, datetime(2026, 1, 15, 4, 30, tzinfo=UTC))
    assert clock.user_today(new_york) == date(2026, 1, 14)
    _frozen_now(monkeypatch, datetime(2026, 7, 15, 4, 30, tzinfo=UTC))
    assert clock.user_today(new_york) == date(2026, 7, 15)


def test_unknown_zone_names_fall_back_to_the_default_and_are_not_choosable():
    assert clock.zone("Mars/Olympus_Mons") is clock.DEFAULT_ZONE
    assert clock.zone(None) is clock.DEFAULT_ZONE
    assert clock.zone("Asia/Tokyo") == ZoneInfo("Asia/Tokyo")
    assert clock.is_timezone_name("Europe/Paris") and clock.is_timezone_name("UTC")
    for name in ("Factory", "Mars/Olympus_Mons", "", "asia/taipei", "+08:00", None, 8):
        assert not clock.is_timezone_name(name), name


def test_latest_today_is_the_day_at_utc_plus_fourteen(monkeypatch):
    # 10:30 UTC is 00:30 the next day on the Line Islands, the first calendar to turn over.
    _frozen_now(monkeypatch, datetime(2026, 1, 31, 10, 30, tzinfo=UTC))
    assert clock.latest_today() == date(2026, 2, 1)
    assert clock.local_today(ZoneInfo("Pacific/Kiritimati")) == date(2026, 2, 1)


@pytest.mark.parametrize(("name", "label"), [
    ("Asia/Taipei", "台灣時間"),
    ("Asia/Tokyo", "Asia/Tokyo，UTC+09:00"),
    ("America/St_Johns", "America/St_Johns，UTC-03:30"),
])
def test_zone_label_names_the_wall_clock(name, label):
    assert clock.zone_label(ZoneInfo(name), datetime(2026, 1, 15, tzinfo=UTC)) == label


def test_round_metric_treats_missing_aggregates_as_zero():
    assert round_metric(None) == 0.0
    assert round_metric(12.346) == 12.35
    assert round_metric(66.666, 1) == 66.7


def test_export_filename_uses_the_application_timezone_not_the_server_zone(monkeypatch):
    """SPEC-047, SPEC-147: a UTC server names exports with the account's wall-clock time."""
    from backend import exporting

    _frozen_now(monkeypatch, datetime(2026, 1, 31, 16, 30, 5, tzinfo=UTC))
    assert exporting.export_filename("csv", "all") == "running_shoes_all_20260201_003005.csv"
    assert exporting.export_filename("xlsx", "active", ZoneInfo("Europe/London")) == (
        "running_shoes_active_20260131_163005.xlsx"
    )


def test_account_backup_filename_uses_the_application_timezone(db, user_with_token):
    """v4.7.2, SPEC-147: a backup taken at 16:30 UTC is named for the account's own day."""
    from backend.services.exports import build_account_export

    user, _ = user_with_token
    taken = datetime(2026, 1, 31, 16, 30, 5, tzinfo=UTC)
    _, filename = build_account_export(db, user, now=taken)
    assert filename == "running_shoes_account_20260201_003005.json"
    user.timezone = "America/Los_Angeles"
    db.commit()
    _, filename = build_account_export(db, user, now=taken)
    assert filename == "running_shoes_account_20260131_083005.json"


def test_frontend_export_fallback_names_use_the_local_calendar_day():
    from pathlib import Path

    source = Path("frontend/app-exports.js").read_text(encoding="utf-8")
    assert "toISOString" not in source
    assert source.count("localDateISO()") == 2


def test_only_the_clock_reaches_for_the_default_calendar():
    """SPEC-147: every caller names the account's zone; no backend module counts today without one."""
    import re
    from pathlib import Path

    offenders = []
    for path in sorted(Path("backend").rglob("*.py")):
        if path.name == "clock.py":
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(r"\blocal_(?:today|now)\(\)", source) or "APP_TIMEZONE" in source:
            offenders.append(str(path))
        if re.search(r"timezone\(timedelta\(|ZoneInfo\(\"", source):
            offenders.append(f"{path}: hard-coded zone")
    assert offenders == []
