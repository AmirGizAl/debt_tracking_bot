"""Helpers for accounting tests: records through the real services."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CashAdjustment, Client, Operation, User
from app.domain.currency import Currency
from app.domain.operations import OperationDraft, OperationType
from app.services import cash, operations
from tests.factories import make_client

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
    adj_date: date = TODAY,
) -> CashAdjustment:
    adjustment, _created = await cash.create_adjustment(
        session, owner, request_id or uuid.uuid4(), currency, Decimal(amount), reason, adj_date
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


async def scenarios_1_to_8(session: AsyncSession, owner: User) -> dict[str, Client]:
    """The state of TZ 15.1 after scenarios 1-8 (scenario 8 writes nothing)."""
    azamat = await make_client(session, owner, "Азамат")
    bekzat = await make_client(session, owner, "Бекзат")
    for amount, currency in (
        ("300000", Currency.KGS),
        ("10000", Currency.USD),
        ("2000", Currency.EUR),
        ("500000", Currency.RUB),
        ("1000000", Currency.KZT),
    ):
        await adjust(session, owner, amount, currency, adj_date=date(2026, 9, 1))
    await record(session, owner, azamat, OperationType.LEND, "1000", op_date=date(2026, 9, 1))
    await record(session, owner, azamat, OperationType.REPAY_IN, "400", op_date=date(2026, 9, 10))
    await record(
        session,
        owner,
        bekzat,
        OperationType.BORROW,
        "50000",
        Currency.RUB,
        op_date=date(2026, 9, 12),
    )
    await record(
        session,
        owner,
        bekzat,
        OperationType.REPAY_OUT,
        "20000",
        Currency.RUB,
        op_date=date(2026, 9, 20),
    )
    await record(
        session,
        owner,
        azamat,
        OperationType.REPAY_IN,
        "52500",
        Currency.USD,
        pay_currency=Currency.KGS,
        rate="87.5",
        op_date=date(2026, 9, 27),
    )
    await record(
        session,
        owner,
        bekzat,
        OperationType.REPAY_OUT,
        "300",
        Currency.RUB,
        pay_currency=Currency.USD,
        rate="90",
        op_date=date(2026, 9, 27),
    )
    return {"Азамат": azamat, "Бекзат": bekzat}
