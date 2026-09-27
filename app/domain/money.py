"""Parsing and formatting of amounts and rates. Money is Decimal only, never float."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
NBSP = " "
MINUS = "−"  # typographic minus, as in the spec: "−500 USD"


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


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
