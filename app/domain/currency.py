from enum import StrEnum


class Currency(StrEnum):
    """Supported currencies. Declaration order is the display order everywhere (TZ 4.1)."""

    KGS = "KGS"
    USD = "USD"
    EUR = "EUR"
    RUB = "RUB"
    KZT = "KZT"


CURRENCIES: tuple[Currency, ...] = tuple(Currency)

# KGS is always the quote currency; otherwise the earlier one in this row is the base (TZ 4.5).
HOME_CURRENCY = Currency.KGS
BASE_PRIORITY: tuple[Currency, ...] = (Currency.EUR, Currency.USD, Currency.RUB, Currency.KZT)
