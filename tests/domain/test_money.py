from decimal import Decimal

import pytest

from app.domain.errors import InvalidNumber, NumberProblem
from app.domain.money import (
    format_amount,
    format_money,
    format_rate,
    format_signed,
    parse_amount,
    parse_rate,
)

NBSP = " "


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1000", "1000.00"),
        ("1 000", "1000.00"),
        ("1000,5", "1000.50"),
        ("1000.50", "1000.50"),
        ("1 000,50", "1000.50"),
        (f"1{NBSP}000{NBSP}000", "1000000.00"),
        ("1 000", "1000.00"),  # narrow no-break space
        ("  52 500 ", "52500.00"),
        ("0,01", "0.01"),
        ("007", "7.00"),
        ("999 999 999 999,99", "999999999999.99"),
    ],
)
def test_parse_amount_accepts(text: str, expected: str) -> None:
    value = parse_amount(text)
    assert value == Decimal(expected)
    assert isinstance(value, Decimal)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("0", NumberProblem.NOT_POSITIVE),
        ("0,00", NumberProblem.NOT_POSITIVE),
        ("-100", NumberProblem.NOT_POSITIVE),
        ("−100", NumberProblem.NOT_POSITIVE),
        ("1000,555", NumberProblem.PRECISION),
        ("0,001", NumberProblem.PRECISION),
        ("abc", NumberProblem.FORMAT),
        ("10 USD", NumberProblem.FORMAT),
        ("1,000.50", NumberProblem.FORMAT),
        ("1e5", NumberProblem.FORMAT),
        ("", NumberProblem.FORMAT),
        ("   ", NumberProblem.FORMAT),
        (",5", NumberProblem.FORMAT),
        ("1 000 000 000 000", NumberProblem.TOO_LARGE),
    ],
)
def test_parse_amount_rejects(text: str, problem: NumberProblem) -> None:
    with pytest.raises(InvalidNumber) as error:
        parse_amount(text)
    assert error.value.problem == problem


@pytest.mark.parametrize(
    ("text", "expected"),
    [("87,5", "87.5"), ("0.17", "0.17"), ("90", "90"), ("0,000001", "0.000001")],
)
def test_parse_rate_accepts(text: str, expected: str) -> None:
    assert parse_rate(text) == Decimal(expected)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("0", NumberProblem.NOT_POSITIVE),
        ("-87,5", NumberProblem.NOT_POSITIVE),
        ("0,0000001", NumberProblem.PRECISION),
        ("восемь", NumberProblem.FORMAT),
    ],
)
def test_parse_rate_rejects(text: str, problem: NumberProblem) -> None:
    with pytest.raises(InvalidNumber) as error:
        parse_rate(text)
    assert error.value.problem == problem


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1000", "1 000"),
        ("1000.5", "1 000,50"),
        ("1000.50", "1 000,50"),
        ("0", "0"),
        ("12", "12"),
        ("352500", "352 500"),
        ("1000000", "1 000 000"),
        ("2101750.00", "2 101 750"),
        ("11.43", "11,43"),
        ("-3000", "−3 000"),
    ],
)
def test_format_amount(value: str, expected: str) -> None:
    assert format_amount(Decimal(value), sep=" ") == expected


def test_format_amount_uses_no_break_space_by_default() -> None:
    assert format_amount(Decimal("1000")) == f"1{NBSP}000"
    assert format_money(Decimal("1000.5"), "USD") == f"1{NBSP}000,50 USD"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("87.5", "87,5"), ("0.17", "0,17"), ("90", "90"), ("90.000000", "90"), ("1000.5", "1 000,5")],
)
def test_format_rate_drops_trailing_zeros(value: str, expected: str) -> None:
    assert format_rate(Decimal(value), sep=" ") == expected


@pytest.mark.parametrize(("value", "expected"), [("1000", "+1 000"), ("-500", "−500"), ("0", "0")])
def test_format_signed(value: str, expected: str) -> None:
    assert format_signed(Decimal(value), sep=" ") == expected
