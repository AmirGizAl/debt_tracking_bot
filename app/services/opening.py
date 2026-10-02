"""Opening balances (TZ 9): the starting point of the surplus.

They are entered and cancelled only before the first closing of a day; one record per
currency that is not cancelled (agreed on 02.10.2026).
"""

import uuid
from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import BusinessDay, DayStatus, Operation, OperationEntry, User
from app.domain.currency import CURRENCIES, Currency
from app.domain.entries import EntryKind, OperationType, opening_draft
from app.domain.errors import BaselineFrozen, OpeningExists
from app.services import ledger
from app.services.users import require_owner

ZERO = Decimal("0.00")


async def baseline_frozen(session: AsyncSession) -> bool:
    """True once any day has been closed."""
    return bool(
        await session.scalar(select(exists().where(BusinessDay.status == DayStatus.CLOSED)))
    )


async def baseline(session: AsyncSession) -> dict[Currency, Decimal]:
    """base(c): cash entries of opening records, cancellations included (TZ 9)."""
    rows = await session.execute(
        select(OperationEntry.currency, func.sum(OperationEntry.delta))
        .join(Operation, Operation.id == OperationEntry.operation_id)
        .where(Operation.type == OperationType.OPENING, OperationEntry.kind == EntryKind.CASH)
        .group_by(OperationEntry.currency)
    )
    totals = {currency: total for currency, total in rows}
    return {currency: totals.get(currency, ZERO) for currency in CURRENCIES}


async def active_opening(session: AsyncSession, currency: Currency) -> Operation | None:
    """The opening record of the currency that is not cancelled, if any."""
    reversal = aliased(Operation)
    return await session.scalar(
        select(Operation).where(
            Operation.type == OperationType.OPENING,
            Operation.currency == currency,
            Operation.reversal_of_id.is_(None),
            ~exists().where(reversal.reversal_of_id == Operation.id),
        )
    )


async def create_opening(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    currency: Currency,
    amount: Decimal,
) -> tuple[Operation, bool]:
    """Raises BaselineFrozen after the first closing, OpeningExists for a second record."""
    require_owner(actor)
    draft = opening_draft(currency, amount)

    async def check(tx: AsyncSession) -> None:
        if await baseline_frozen(tx):
            raise BaselineFrozen()
        if await active_opening(tx, currency) is not None:
            raise OpeningExists(currency)

    # The lock of the currency also keeps two owners from entering it at the same moment.
    return await ledger.post(session, actor, request_id, draft, lock_also=[currency], check=check)
