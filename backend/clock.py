"""Application calendar clock: the single definition of an account's local "today" (SPEC-147).

Calendar rules (future-date checks, goals, forecasts, streaks, reports) evaluate "today" in
the signed-in account's IANA zone. Every account starts in Asia/Taipei, the one zone the
service used before SPEC-147, so existing accounts keep their calendar. No other module
hard-codes an offset or reads the server's zone.
"""

from datetime import date, datetime, timedelta, timezone, tzinfo
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

DEFAULT_TIMEZONE = "Asia/Taipei"
DEFAULT_ZONE = ZoneInfo(DEFAULT_TIMEZONE)
# The longest IANA name is 32 characters; the column and the request allow twice that.
MAX_TIMEZONE_LENGTH = 64
# tzdata ships "Factory" as a placeholder, not a place anyone lives.
_NOT_PLACES = frozenset({"Factory"})
# The calendar runs furthest ahead at UTC+14 (Line Islands): no account is on a later day.
_EARLIEST_ZONE = timezone(timedelta(hours=14))


@cache
def timezone_names() -> frozenset[str]:
    """The IANA zone names an account may choose."""
    return frozenset(available_timezones()) - _NOT_PLACES


def is_timezone_name(value: object) -> bool:
    return isinstance(value, str) and value in timezone_names()


@cache
def zone(name: str | None) -> ZoneInfo:
    """The zone of a stored name; a missing or no longer known name uses the default."""
    return ZoneInfo(name) if name is not None and is_timezone_name(name) else DEFAULT_ZONE


def zone_for(user: object) -> ZoneInfo:
    """The calendar zone of an account row (anything with a `timezone` attribute)."""
    return zone(getattr(user, "timezone", None))


def local_now(tz: tzinfo = DEFAULT_ZONE) -> datetime:
    return datetime.now(tz)


def local_today(tz: tzinfo = DEFAULT_ZONE) -> date:
    return local_now(tz).date()


def user_today(user: object) -> date:
    """The account's calendar day right now."""
    return local_today(zone_for(user))


def latest_today() -> date:
    """The latest calendar day any account can be on right now (UTC+14).

    Request schemas do not know the account, so they reject only dates past every zone's
    today; the services check the account's own today.
    """
    return datetime.now(_EARLIEST_ZONE).date()


def zone_label(tz: ZoneInfo, instant: datetime) -> str:
    """How a message names the account's wall clock: 台灣時間, or the zone with its offset then."""
    if tz.key == DEFAULT_TIMEZONE:
        return "台灣時間"
    offset = instant.astimezone(tz).strftime("%z")
    return f"{tz.key}，UTC{offset[:3]}:{offset[3:]}"
