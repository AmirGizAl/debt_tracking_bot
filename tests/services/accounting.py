"""Helpers for accounting tests: records through the real services."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CashAdjustment, Client, Operation, User
from app.domain.currency import Currency
from app.domain.operations import OperationDraft, OperationType
from app.services import cash, operations

TODAY = date(2026, 9, 27)


async def record(
    session: AsyncSession,
    actor: User,
    client: Client,
    op_type: OperationType,
    amount: str,
    currency: Currency = Currency.USD,
    *,
    pay_currency: Currency | None = None,
    rate: str | None = None,
    op_date: date = TODAY,
    request_id: uuid.UUID | None = None,
    comment: str | None = None,
) -> Operation:
    """`amount` is the money that moved (in `pay_currency`, default: the debt currency)."""
    draft = OperationDraft(
        request_id=request_id or uuid.uuid4(),
        type=op_type,
        client_id=client.id,
        debt_currency=currency,
        cash_currency=pay_currency or currency,
        cash_amount=Decimal(amount),
        op_date=op_date,
        rate=Decimal(rate) if rate is not None else None,
        comment=comment,
    )
    operation, _created = await operations.create_operation(session, actor, draft)
    return operation


async def adjust(
    session: AsyncSession,
    owner: User,
    amount: str,
    currency: Currency = Currency.USD,
    reason: str = "Остаток на начало работы",
    *,
    request_id: uuid.UUID | None = None,
) -> CashAdjustment:
    adjustment, _created = await cash.create_adjustment(
        session, owner, request_id or uuid.uuid4(), currency, Decimal(amount), reason, TODAY
    )
    return adjustment


async def reverse(
    session: AsyncSession,
    actor: User,
    operation: Operation,
    reason: str = "ошибка в сумме",
    *,
    request_id: uuid.UUID | None = None,
) -> Operation:
    reversal, _created = await operations.reverse_operation(
        session, actor, request_id or uuid.uuid4(), operation.id, reason, TODAY
    )
    return reversal
