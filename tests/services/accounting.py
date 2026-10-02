"""Records through the real services, for accounting tests."""

import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Operation, User
from app.domain.currency import Currency
from app.domain.entries import ExchangeTerms, OperationType
from app.services import adjustments, exchange, loans, opening, reversal, settlements

USD, EUR, RUB, KZT, KGS = (
    Currency.USD,
    Currency.EUR,
    Currency.RUB,
    Currency.KZT,
    Currency.KGS,
)
D = Decimal


async def open_balance(
    session: AsyncSession, owner: User, amount: str, currency: Currency
) -> Operation:
    record, _ = await opening.create_opening(session, owner, uuid.uuid4(), currency, D(amount))
    return record


async def swap(
    session: AsyncSession,
    actor: User,
    give: str,
    give_currency: Currency,
    get: str,
    get_currency: Currency,
    *,
    rate: str | None = None,
    received_now: bool = True,
    paid_now: bool = True,
    client: Client | None = None,
    request_id: uuid.UUID | None = None,
) -> Operation:
    """An exchange: the client gives `give` and gets `get`."""
    terms = ExchangeTerms(
        give_currency=give_currency,
        give_amount=D(give),
        get_currency=get_currency,
        get_amount=D(get),
        received_now=received_now,
        paid_now=paid_now,
        rate=D(rate) if rate is not None else None,
    )
    record, _ = await exchange.create_exchange(
        session, actor, request_id or uuid.uuid4(), terms, client.id if client else None
    )
    return record


async def settle(
    session: AsyncSession,
    actor: User,
    op_type: OperationType,
    client: Client,
    amount: str,
    currency: Currency,
) -> Operation:
    record, _ = await settlements.create_settlement(
        session, actor, uuid.uuid4(), op_type, client.id, currency, D(amount)
    )
    return record


async def loan(
    session: AsyncSession, actor: User, op_type: OperationType, client: Client, amount: str
) -> Operation:
    record, _ = await loans.create_loan(session, actor, uuid.uuid4(), op_type, client.id, D(amount))
    return record


async def adjust(
    session: AsyncSession, owner: User, amount: str, currency: Currency, reason: str = "пересчёт"
) -> Operation:
    record, _ = await adjustments.create_adjustment(
        session, owner, uuid.uuid4(), currency, D(amount), reason
    )
    return record


async def cancel(
    session: AsyncSession, actor: User, record: Operation, reason: str = "ошибка"
) -> Operation:
    result, _ = await reversal.reverse(session, actor, uuid.uuid4(), record.id, reason)
    return result


async def force_close_day(session: AsyncSession, owner: User) -> None:
    """Close the open day and open the next one, bypassing the closing service."""
    await session.execute(
        text(
            "UPDATE business_days SET status = 'closed', closed_at = now(), closed_by_id = :owner,"
            " rates = '{}', report = '{}', surplus = 0 WHERE status = 'open'"
        ),
        {"owner": owner.id},
    )
    await session.execute(text("INSERT INTO business_days (status) VALUES ('open')"))
    await session.commit()
