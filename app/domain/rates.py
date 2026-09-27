"""Rate direction and conversion of a payment into the debt currency (TZ 4.5, 4.6).

A rate is always "1 base = rate quote". Pure functions, no database.
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.domain.currency import BASE_PRIORITY, HOME_CURRENCY, Currency
from app.domain.errors import ConversionProblem, InvalidConversion
from app.domain.money import CENT, MAX_AMOUNT

# Enough digits that the only rounding is the final ROUND_HALF_UP to cents
# (the default 28 digits could round 12-digit amounts twice).
_PRECISION = 60


def rate_pair(first: Currency, second: Currency) -> tuple[Currency, Currency]:
    """(base, quote) for two different currencies.

    KGS is always the quote; otherwise the currency earlier in EUR, USD, RUB, KZT is the base.
    """
    if first == second:
        raise ValueError(f"a rate needs two different currencies, got {first} twice")
    if HOME_CURRENCY in (first, second):
        base = second if first == HOME_CURRENCY else first
        return base, HOME_CURRENCY
    base, quote = sorted((first, second), key=BASE_PRIORITY.index)
    return base, quote


def convert_payment(
    pay_amount: Decimal, pay_currency: Currency, debt_currency: Currency, rate: Decimal
) -> Decimal:
    """How much of the debt a payment covers, rounded half up to cents.

    Paying in the base currency multiplies by the rate, paying in the quote divides.
    """
    base, _quote = rate_pair(pay_currency, debt_currency)
    with localcontext() as context:
        context.prec = _PRECISION
        raw = pay_amount * rate if pay_currency == base else pay_amount / rate
        debt_amount = raw.quantize(CENT, rounding=ROUND_HALF_UP)
    if debt_amount == 0:
        raise InvalidConversion(ConversionProblem.ZERO)
    if debt_amount > MAX_AMOUNT:
        raise InvalidConversion(ConversionProblem.TOO_LARGE)
    return debt_amount
