"""Record dates (TZ 7.6) and report periods (TZ 12.8). "Today" is in the TZ time zone."""

import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.errors import FutureDate, InvalidDate

_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?")


def today(zone: ZoneInfo) -> date:
    return datetime.now(zone).date()


def parse_date(text: str, current: date, allow_future: bool = False) -> date:
    """'25.09.2026' or '25.09' (current year). Future dates are refused unless allowed."""
    match = _DATE.fullmatch(text.strip())
    if match is None:
        raise InvalidDate(text)
    day, month, year = match.groups()
    try:
        value = date(int(year) if year else current.year, int(month), int(day))
    except ValueError as exc:
        raise InvalidDate(text) from exc
    if not allow_future and value > current:
        raise FutureDate(text)
    return value


def yesterday(current: date) -> date:
    return current - timedelta(days=1)


def month_bounds(day: date) -> tuple[date, date]:
    last = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last)


def previous_month_bounds(day: date) -> tuple[date, date]:
    return month_bounds(day.replace(day=1) - timedelta(days=1))


def year_start(day: date) -> date:
    return day.replace(month=1, day=1)


def format_date(value: date) -> str:
    return f"{value:%d.%m.%Y}"


def format_short_date(value: date) -> str:
    return f"{value:%d.%m}"


def format_datetime(value: datetime, zone: ZoneInfo) -> str:
    return f"{value.astimezone(zone):%d.%m.%Y %H:%M}"
