"""Records through the real services, for accounting tests."""

import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Operation, User
from app.domain.currency import Currency
from app.domain.entries import ExchangeTerms, OperationType
from app.services import adjustments, exchange, loans, opening, reversal, settlements
from tests.factories import make_client

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


DAY_1_RATES = {Currency.USD: D("87.65"), Currency.RUB: D("0.991")}
DAY_2_RATES = {Currency.USD: D("87.70"), Currency.RUB: D("0.99")}


async def acceptance_day_1(session: AsyncSession, owner: User) -> dict[str, Client]:
    """TZ 17.1, scenarios 1-5: the state of the control example 8.6."""
    azamat = await make_client(session, owner, "Азамат")
    bekzat = await make_client(session, owner, "Бекзат")
    await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    await swap(session, owner, "1000", USD, "87000", KGS, rate="87")
    await swap(session, owner, "88000", KGS, "1000", USD, rate="88")
    await swap(
        session, owner, "88500", RUB, "1000", USD, rate="88.5", paid_now=False, client=azamat
    )
    await loan(session, owner, OperationType.LOAN_GIVE, bekzat, "50000")
    return {"Азамат": azamat, "Бекзат": bekzat}


async def acceptance_day_2(session: AsyncSession, owner: User, azamat: Client) -> None:
    """TZ 17.1, scenarios 9 and 10."""
    await settle(session, owner, OperationType.EXCHANGE_PAYOUT, azamat, "1000", USD)
    await swap(session, owner, "2000", USD, "175000", KGS, rate="87.5")


async def acceptance_day_3(
    session: AsyncSession, owner: User, helper: User, bekzat: Client
) -> Client:
    """TZ 17.1, scenarios 12-14 (Айгуль is `helper`); returns Тимур."""
    timur = await make_client(session, owner, "Тимур")
    await swap(session, owner, "100000", RUB, "99000", RUB, paid_now=False, client=timur)
    await swap(
        session, owner, "99000", RUB, "98010", KGS, rate="0.99", received_now=False, client=timur
    )
    wrong = await loan(session, helper, OperationType.LOAN_REPAY_IN, bekzat, "5000")
    await cancel(session, helper, wrong, "ошибка в сумме")
    await loan(session, helper, OperationType.LOAN_REPAY_IN, bekzat, "50000")
    return timur
