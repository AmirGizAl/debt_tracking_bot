"""Parsing and formatting of amounts and rates (TZ 4.2-4.4). Decimal only, never float."""

import re
from decimal import ROUND_HALF_UP, Decimal

from app.domain.errors import InvalidNumber, NumberProblem

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("999999999999.99")
MAX_RATE = Decimal("999999999999.999999")  # NUMERIC(18,6)
AMOUNT_PLACES = 2
RATE_PLACES = 6

NBSP = " "
MINUS = "−"  # typographic minus, as in the spec: "−500 USD"

_SPACES = re.compile(r"\s+")  # any Unicode space, including no-break ones
_NUMBER = re.compile(r"[0-9]+(?:\.([0-9]+))?")


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _parse_positive(text: str, places: int, maximum: Decimal) -> Decimal:
    cleaned = _SPACES.sub("", text).replace(",", ".")
    negative = cleaned[:1] in ("-", MINUS)
    if negative:
        cleaned = cleaned[1:]
    match = _NUMBER.fullmatch(cleaned)
    if match is None:
        raise InvalidNumber(NumberProblem.FORMAT)
    fraction = match.group(1)
    if fraction is not None and len(fraction) > places:
        # More digits than allowed is a typo, not something to round (TZ 4.2).
        raise InvalidNumber(NumberProblem.PRECISION)
    value = Decimal(cleaned)
    if negative or value <= 0:
        raise InvalidNumber(NumberProblem.NOT_POSITIVE)
    if value > maximum:
        raise InvalidNumber(NumberProblem.TOO_LARGE)
    return value


def parse_amount(text: str) -> Decimal:
    """'1 000,50' -> Decimal('1000.50'). Raises InvalidNumber."""
    return quantize_money(_parse_positive(text, AMOUNT_PLACES, MAX_AMOUNT))


def parse_rate(text: str) -> Decimal:
    """'87,5' -> Decimal('87.5'); up to six decimal places. Raises InvalidNumber."""
    return _parse_positive(text, RATE_PLACES, MAX_RATE)


def _group_thousands(digits: str, sep: str) -> str:
    head = len(digits) % 3 or 3
    groups = [digits[:head]] + [digits[i : i + 3] for i in range(head, len(digits), 3)]
    return sep.join(groups)


def format_amount(value: Decimal, sep: str = NBSP) -> str:
    """1000 -> '1 000', 1000.5 -> '1 000,50', -500 -> '−500' (TZ 4.4)."""
    value = quantize_money(value)
    sign = MINUS if value < 0 else ""
    integer, fraction = f"{abs(value):.2f}".split(".")
    text = _group_thousands(integer, sep)
    if fraction != "00":
        text += f",{fraction}"
    return sign + text


def format_signed(value: Decimal, sep: str = NBSP) -> str:
    """'+1 000' / '−500' / '0' for movements."""
    text = format_amount(value, sep)
    return f"+{text}" if quantize_money(value) > 0 else text


def format_money(value: Decimal, currency: str, sep: str = NBSP) -> str:
    return f"{format_amount(value, sep)} {currency}"


def format_rate(value: Decimal, sep: str = NBSP) -> str:
    """87.500000 -> '87,5', 0.17 -> '0,17', 90 -> '90', 1000.5 -> '1 000,5' (TZ 4.4)."""
    integer, fraction = f"{value:.6f}".split(".")
    fraction = fraction.rstrip("0")
    text = _group_thousands(integer, sep)
    return f"{text},{fraction}" if fraction else text
