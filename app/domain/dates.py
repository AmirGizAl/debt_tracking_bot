from datetime import date, datetime
from zoneinfo import ZoneInfo


def format_date(value: date) -> str:
    return f"{value:%d.%m.%Y}"


def format_short_date(value: date) -> str:
    return f"{value:%d.%m}"


def format_datetime(value: datetime, zone: ZoneInfo) -> str:
    return f"{value.astimezone(zone):%d.%m.%Y %H:%M}"


def today(zone: ZoneInfo) -> date:
    return datetime.now(zone).date()
