from enum import StrEnum


class Currency(StrEnum):
    """Supported currencies. Declaration order is the display order everywhere (TZ 4.1)."""

    USD = "USD"
    EUR = "EUR"
    RUB = "RUB"
    KZT = "KZT"
    KGS = "KGS"


CURRENCIES: tuple[Currency, ...] = tuple(Currency)

# Som cash ("наличка") is KGS; the other four are the currency balances (TZ 4.1).
HOME_CURRENCY = Currency.KGS
FOREIGN_CURRENCIES: tuple[Currency, ...] = tuple(c for c in Currency if c != HOME_CURRENCY)

# KGS is always the quote currency; otherwise the earlier one in this row is the base (TZ 4.5).
BASE_PRIORITY: tuple[Currency, ...] = (Currency.EUR, Currency.USD, Currency.RUB, Currency.KZT)
