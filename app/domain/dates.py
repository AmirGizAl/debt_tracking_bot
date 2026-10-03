"""Dates in the TZ time zone: records are dated "today" there, report periods end today."""

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.errors import InvalidDate

_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def today(zone: ZoneInfo) -> date:
    return datetime.now(zone).date()


def parse_date(raw: str) -> date:
    """ "01.10.2026" (TZ 13.10, «Период по датам»); anything else raises InvalidDate."""
    match = _DATE.fullmatch(raw.strip())
    if match is None:
        raise InvalidDate(raw)
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError as exc:  # 31.02.2026
        raise InvalidDate(raw) from exc


def day_bounds(start: date, end: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """[start 00:00, the day after end 00:00) in the zone: both dates are included."""
    return (
        datetime.combine(start, time(), tzinfo=zone),
        datetime.combine(end + timedelta(days=1), time(), tzinfo=zone),
    )


def format_date(value: date) -> str:
    return f"{value:%d.%m.%Y}"


def format_short_date(value: date) -> str:
    return f"{value:%d.%m}"


def format_datetime(value: datetime, zone: ZoneInfo) -> str:
    return f"{value.astimezone(zone):%d.%m.%Y %H:%M}"
