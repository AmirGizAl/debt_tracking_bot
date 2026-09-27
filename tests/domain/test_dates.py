from datetime import date

import pytest

from app.domain.dates import month_bounds, parse_date, previous_month_bounds, year_start
from app.domain.errors import FutureDate, InvalidDate

TODAY = date(2026, 9, 27)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("25.09.2026", date(2026, 9, 25)),
        ("25.09", date(2026, 9, 25)),
        (" 1.9 ", date(2026, 9, 1)),
        ("27.09.2026", TODAY),
        ("31.12.2025", date(2025, 12, 31)),
    ],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize(
    "text", ["", "завтра", "32.09.2026", "29.02.2026", "25-09-2026", "25.09.26"]
)
def test_parse_date_rejects_garbage(text: str) -> None:
    with pytest.raises(InvalidDate):
        parse_date(text, TODAY)


@pytest.mark.parametrize("text", ["28.09.2026", "28.09", "01.01.2027"])
def test_future_dates_are_refused(text: str) -> None:
    with pytest.raises(FutureDate):
        parse_date(text, TODAY)


def test_future_dates_allowed_for_report_periods() -> None:
    assert parse_date("30.09.2026", TODAY, allow_future=True) == date(2026, 9, 30)


def test_period_bounds() -> None:
    assert month_bounds(TODAY) == (date(2026, 9, 1), date(2026, 9, 30))
    assert previous_month_bounds(TODAY) == (date(2026, 8, 1), date(2026, 8, 31))
    assert previous_month_bounds(date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert month_bounds(date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert year_start(TODAY) == date(2026, 1, 1)
