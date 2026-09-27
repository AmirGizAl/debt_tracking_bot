"""Client balances are never stored: they are sums over the journal (TZ 6.5, 7.2)."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Operation
from app.domain.currency import CURRENCIES, Currency

ZERO = Decimal("0.00")


async def client_balances(session: AsyncSession, client_id: int) -> dict[Currency, Decimal]:
    """Balance per currency (all five, zeros included). Positive: the client owes the owner."""
    rows = await session.execute(
        select(Operation.debt_currency, func.sum(Operation.debt_delta))
        .where(Operation.client_id == client_id)
        .group_by(Operation.debt_currency)
    )
    balances = dict.fromkeys(CURRENCIES, ZERO)
    for currency, total in rows:
        balances[currency] = total
    return balances


async def client_balance(session: AsyncSession, client_id: int, currency: Currency) -> Decimal:
    total = await session.scalar(
        select(func.sum(Operation.debt_delta)).where(
            Operation.client_id == client_id, Operation.debt_currency == currency
        )
    )
    return total if total is not None else ZERO
