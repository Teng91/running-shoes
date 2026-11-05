"""Application calendar clock: the single definition of the service's local "today"."""

from datetime import date, datetime, timedelta, timezone

# Users are in Taiwan; calendar rules (future-date checks, goals, forecasts, reports)
# all evaluate "today" in this fixed UTC+8 zone.
APP_TIMEZONE = timezone(timedelta(hours=8))


def local_today() -> date:
    return datetime.now(APP_TIMEZONE).date()
