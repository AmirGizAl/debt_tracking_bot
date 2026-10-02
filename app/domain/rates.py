"""Rate direction and conversion by a rate (TZ 4.5, 4.6).

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


def convert(known: Decimal, known_currency: Currency, other: Currency, rate: Decimal) -> Decimal:
    """The amount in `other` for `known` in `known_currency`, rounded half up to cents.

    A known amount in the base currency is multiplied by the rate, in the quote one divided.
    """
    base, _quote = rate_pair(known_currency, other)
    with localcontext() as context:
        context.prec = _PRECISION
        raw = known * rate if known_currency == base else known / rate
        result = raw.quantize(CENT, rounding=ROUND_HALF_UP)
    if result == 0:
        raise InvalidConversion(ConversionProblem.ZERO)
    if result > MAX_AMOUNT:
        raise InvalidConversion(ConversionProblem.TOO_LARGE)
    return result
