from decimal import Decimal
from fractions import Fraction

import pytest

from app.bot.texts import rate_question
from app.domain.currency import Currency
from app.domain.errors import ConversionProblem, InvalidConversion
from app.domain.rates import convert, rate_pair

KGS, USD, EUR, RUB, KZT = Currency.KGS, Currency.USD, Currency.EUR, Currency.RUB, Currency.KZT

# The full table of TZ 4.5: (pair) -> (base, quote, question).
PAIRS = [
    (USD, KGS, "Сколько сомов за 1 USD?"),
    (EUR, KGS, "Сколько сомов за 1 EUR?"),
    (RUB, KGS, "Сколько сомов за 1 RUB?"),
    (KZT, KGS, "Сколько сомов за 1 KZT?"),
    (EUR, USD, "Сколько USD за 1 EUR?"),
    (EUR, RUB, "Сколько RUB за 1 EUR?"),
    (EUR, KZT, "Сколько KZT за 1 EUR?"),
    (USD, RUB, "Сколько RUB за 1 USD?"),
    (USD, KZT, "Сколько KZT за 1 USD?"),
    (RUB, KZT, "Сколько KZT за 1 RUB?"),
]


@pytest.mark.parametrize(("base", "quote", "question"), PAIRS)
def test_rate_pair_table(base: Currency, quote: Currency, question: str) -> None:
    # The direction does not depend on which currency is the debt and which is the payment.
    assert rate_pair(base, quote) == (base, quote)
    assert rate_pair(quote, base) == (base, quote)
    assert rate_question(base, quote) == question


def test_table_covers_every_pair() -> None:
    pairs = {frozenset((base, quote)) for base, quote, _ in PAIRS}
    assert len(pairs) == 10  # C(5, 2)


def test_rate_pair_needs_two_currencies() -> None:
    with pytest.raises(ValueError, match="two different currencies"):
        rate_pair(USD, USD)


# TZ 4.6 control examples: (known amount, its currency, rate) -> the other amount.
@pytest.mark.parametrize(
    ("known", "known_currency", "other", "rate", "expected"),
    [
        ("1000", USD, KGS, "87", "87000"),
        ("88000", KGS, USD, "88", "1000"),
        ("88500", RUB, USD, "88.5", "1000"),
        ("1000", KGS, USD, "87.5", "11.43"),
        ("900", EUR, USD, "1.1", "990"),
        ("100000", KZT, KGS, "0.17", "17000"),
    ],
)
def test_convert_examples(
    known: str, known_currency: Currency, other: Currency, rate: str, expected: str
) -> None:
    result = convert(Decimal(known), known_currency, other, Decimal(rate))
    assert result == Decimal(expected)
    assert result.as_tuple().exponent == -2


def test_conversion_rounds_half_up() -> None:
    # 0.01 / 2 = 0.005 -> 0.01 (banker's rounding would give 0.00).
    assert convert(Decimal("0.01"), KGS, USD, Decimal("2")) == Decimal("0.01")
    # 1.00 / 0.8 = 1.25 exactly stays, 1.00 / 3 = 0.333.. -> 0.33, 2 / 3 = 0.666.. -> 0.67
    assert convert(Decimal("1"), KGS, USD, Decimal("3")) == Decimal("0.33")
    assert convert(Decimal("2"), KGS, USD, Decimal("3")) == Decimal("0.67")


def test_conversion_to_zero_is_an_input_error() -> None:
    with pytest.raises(InvalidConversion) as error:
        convert(Decimal("0.01"), KGS, USD, Decimal("3"))
    assert error.value.problem == ConversionProblem.ZERO


def test_conversion_above_the_maximum_is_an_input_error() -> None:
    with pytest.raises(InvalidConversion) as error:
        convert(Decimal("999999999999.99"), USD, KGS, Decimal("1000"))
    assert error.value.problem == ConversionProblem.TOO_LARGE


def _exact_half_up(value: Fraction) -> Decimal:
    cents = value * 100
    whole = cents.numerator // cents.denominator
    if cents - whole >= Fraction(1, 2):
        whole += 1
    return Decimal(whole) / 100


@pytest.mark.parametrize(
    ("pay", "pay_currency", "debt", "rate"),
    [
        ("999999999999.99", KGS, USD, "87.5"),
        ("123456789012.34", KGS, USD, "0.123457"),
        ("999999999999.99", KGS, USD, "999999.999999"),
        ("98765432.10", USD, KGS, "10123.456789"),
        ("0.05", KGS, USD, "0.1"),
        ("1", KZT, RUB, "0.000001"),
    ],
)
def test_conversion_is_exact_for_large_values(
    pay: str, pay_currency: Currency, debt: Currency, rate: str
) -> None:
    # The default 28-digit Decimal context could round such values twice.
    base, _ = rate_pair(pay_currency, debt)
    exact = (
        Fraction(pay) * Fraction(rate) if pay_currency == base else Fraction(pay) / Fraction(rate)
    )
    assert convert(Decimal(pay), pay_currency, debt, Decimal(rate)) == _exact_half_up(exact)
