from datetime import date

import pytest

from app.domain.dates import last_days

TODAY = date(2026, 9, 27)


@pytest.mark.parametrize(
    ("days", "start"),
    [
        (1, TODAY),
        (7, date(2026, 9, 21)),
        (30, date(2026, 8, 29)),
        (365, date(2025, 9, 28)),
    ],
)
def test_last_days_include_today(days: int, start: date) -> None:
    assert last_days(TODAY, days) == (start, TODAY)
    assert (TODAY - start).days + 1 == days


def test_last_days_cross_a_leap_day() -> None:
    assert last_days(date(2028, 3, 1), 2) == (date(2028, 2, 29), date(2028, 3, 1))
