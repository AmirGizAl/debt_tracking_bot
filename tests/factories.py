"""Direct inserts for test setup (bypassing services where a test needs exact control)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CashAdjustment, Client, Operation, User
from app.domain.currency import Currency
from app.domain.operations import OperationType

DEBT_SIGN = {
    OperationType.LEND: 1,
    OperationType.REPAY_IN: -1,
    OperationType.BORROW: -1,
    OperationType.REPAY_OUT: 1,
}


async def make_client(
    session: AsyncSession,
    author: User,
    name: str,
    *,
    comment: str | None = None,
    created_at: datetime | None = None,
) -> Client:
    client = Client(name=name, comment=comment, created_by_id=author.id)
    if created_at is not None:
        client.created_at = created_at
    session.add(client)
    await session.commit()
    return client


async def make_operation(
    session: AsyncSession,
    author: User,
    client: Client,
    op_type: OperationType,
    amount: str,
    currency: Currency = Currency.USD,
    *,
    op_date: date = date(2026, 9, 1),
    created_at: datetime | None = None,
) -> Operation:
    """A same-currency record with deltas by TZ 7.1."""
    value = Decimal(amount)
    sign = DEBT_SIGN[op_type]
    operation = Operation(
        request_id=uuid.uuid4(),
        type=op_type,
        client_id=client.id,
        debt_currency=currency,
        debt_amount=value,
        cash_currency=currency,
        cash_amount=value,
        debt_delta=sign * value,
        cash_delta=-sign * value,
        op_date=op_date,
        author_id=author.id,
    )
    if created_at is not None:
        operation.created_at = created_at
    session.add(operation)
    await session.commit()
    return operation


async def make_adjustment(
    session: AsyncSession,
    author: User,
    amount: str,
    currency: Currency = Currency.USD,
    *,
    reason: str = "Остаток на начало работы",
    adj_date: date = date(2026, 9, 1),
) -> CashAdjustment:
    adjustment = CashAdjustment(
        request_id=uuid.uuid4(),
        currency=currency,
        amount=Decimal(amount),
        reason=reason,
        adj_date=adj_date,
        author_id=author.id,
    )
    session.add(adjustment)
    await session.commit()
    return adjustment
