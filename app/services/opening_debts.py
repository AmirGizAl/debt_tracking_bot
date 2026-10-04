"""Opening debts (agreed with the customer on 03.10.2026): debts from before the bot.

An obligation of a client without money: owners only, on any day. Like the opening balances
they belong to the starting point of the surplus, so they never show as a profit. One record
that is not cancelled per client, book and currency; a mistake is fixed by its cancellation.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Client, Operation, OperationEntry, User
from app.domain.currency import Currency
from app.domain.entries import (
    OPENING_DEBT_TYPE,
    OPENING_DEBT_TYPES,
    Book,
    EntryKind,
    OperationType,
    opening_debt_draft,
)
from app.domain.errors import OpeningDebtExists
from app.services import ledger
from app.services.users import require_owner


@dataclass(frozen=True)
class OpeningDebt:
    record_id: int
    client: str
    book: Book
    currency: Currency
    amount: Decimal  # above zero the client owes us


def _not_cancelled() -> list[ColumnElement[bool]]:
    reversal = aliased(Operation)
    return [
        Operation.reversal_of_id.is_(None),
        ~exists().where(reversal.reversal_of_id == Operation.id),
    ]


async def debt_baseline(session: AsyncSession) -> dict[Currency, Decimal]:
    """The opening debts of every currency in both books, cancellations included."""
    rows = await session.execute(
        select(OperationEntry.currency, func.sum(OperationEntry.delta))
        .join(Operation, Operation.id == OperationEntry.operation_id)
        .where(
            Operation.type.in_(OPENING_DEBT_TYPES),
            OperationEntry.kind == EntryKind.OBLIGATION,
        )
        .group_by(OperationEntry.currency)
    )
    return {currency: total for currency, total in rows if total != 0}


async def active_debt(
    session: AsyncSession, client_id: int, book: Book, currency: Currency
) -> Operation | None:
    """The opening debt of the client in the book and currency that is not cancelled."""
    return await session.scalar(
        select(Operation).where(
            Operation.type == OPENING_DEBT_TYPE[book],
            Operation.client_id == client_id,
            Operation.currency == currency,
            *_not_cancelled(),
        )
    )


async def active_debts(session: AsyncSession) -> list[OpeningDebt]:
    """Every opening debt that is not cancelled, by the name of the client."""
    rows = await session.execute(
        select(Operation.id, Client.name, Operation.type, Operation.currency, Operation.amount)
        .join(Client, Client.id == Operation.client_id)
        .where(Operation.type.in_(OPENING_DEBT_TYPES), *_not_cancelled())
        .order_by(func.lower(Client.name), Operation.id)
    )
    return [
        OpeningDebt(
            record_id=record_id,
            client=name,
            book=Book.LOAN if op_type == OperationType.OPENING_LOAN else Book.EXCHANGE,
            currency=currency,
            amount=amount,
        )
        for record_id, name, op_type, currency, amount in rows
    ]


async def create_opening_debt(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    client_id: int,
    book: Book,
    currency: Currency,
    amount: Decimal,
) -> tuple[Operation, bool]:
    """`amount` is signed: above zero the client owes us. Raises OpeningDebtExists."""
    require_owner(actor)
    draft = opening_debt_draft(client_id, book, currency, amount)

    async def check(tx: AsyncSession) -> None:
        if await active_debt(tx, client_id, book, currency) is not None:
            raise OpeningDebtExists(currency)

    # The lock of the currency keeps two owners from entering the same debt at once.
    return await ledger.post(session, actor, request_id, draft, lock_also=[currency], check=check)
