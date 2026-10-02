"""Lists of obligations: «Ждут выдачи», «Ждут оплаты» (TZ 13.4) and som loans (TZ 13.5)."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.currency import CURRENCIES, Currency
from app.domain.entries import Book
from app.services import ledger
from app.services.ledger import ObligationLine


def _currency_then_largest(line: ObligationLine) -> tuple[int, Decimal, str, int]:
    return CURRENCIES.index(line.currency), -abs(line.amount), line.client.lower(), line.client_id


async def waiting(session: AsyncSession, paying: bool) -> list[ObligationLine]:
    """«Ждут выдачи» (we owe the client, `paying`) or «Ждут оплаты» (the client owes us).

    Grouped by currency in the display order, the largest amount first within a currency.
    """
    lines = await ledger.obligation_lines(session, Book.EXCHANGE)
    chosen = [line for line in lines if (line.amount < 0) == paying]
    return sorted(chosen, key=_currency_then_largest)


def totals(lines: list[ObligationLine]) -> dict[Currency, Decimal]:
    """The total of every currency (without sign), currencies in the display order."""
    sums: dict[Currency, Decimal] = {}
    for line in lines:
        sums[line.currency] = sums.get(line.currency, Decimal(0)) + abs(line.amount)
    return {currency: sums[currency] for currency in CURRENCIES if currency in sums}


async def loan_debts(session: AsyncSession) -> list[ObligationLine]:
    """«Кто кому должен» of som loans: first who owes us, then whom we owe; largest first."""
    lines = sorted(await ledger.obligation_lines(session, Book.LOAN), key=_currency_then_largest)
    return [line for line in lines if line.amount > 0] + [line for line in lines if line.amount < 0]
