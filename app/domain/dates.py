"""Dates in the TZ time zone: records are dated "today" there, report periods end today."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def today(zone: ZoneInfo) -> date:
    return datetime.now(zone).date()


def last_days(current: date, days: int) -> tuple[date, date]:
    """The last `days` days up to and including `current`."""
    return current - timedelta(days=days - 1), current


def format_date(value: date) -> str:
    return f"{value:%d.%m.%Y}"


def format_short_date(value: date) -> str:
    return f"{value:%d.%m}"


def format_datetime(value: datetime, zone: ZoneInfo) -> str:
    return f"{value.astimezone(zone):%d.%m.%Y %H:%M}"
