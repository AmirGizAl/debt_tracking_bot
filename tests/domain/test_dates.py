"""Dates of «Период по датам» (TZ 13.10)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.dates import day_bounds, parse_date
from app.domain.errors import InvalidDate

MOSCOW = ZoneInfo("Europe/Moscow")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01.10.2026", date(2026, 10, 1)),
        (" 1.10.2026 ", date(2026, 10, 1)),
        ("29.02.2028", date(2028, 2, 29)),
    ],
)
def test_dates_are_read(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "1.10.26", "2026-10-01", "01/10/2026", "31.02.2026", "29.02.2027", "01.13.2026"]
)
def test_wrong_dates_are_refused(raw: str) -> None:
    with pytest.raises(InvalidDate):
        parse_date(raw)


def test_both_dates_of_a_period_are_included() -> None:
    start, end = day_bounds(date(2026, 10, 1), date(2026, 10, 3), MOSCOW)

    assert start == datetime(2026, 10, 1, tzinfo=MOSCOW)
    assert end == datetime(2026, 10, 4, tzinfo=MOSCOW)
