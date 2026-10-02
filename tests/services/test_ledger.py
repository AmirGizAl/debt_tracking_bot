"""The journal and the records (TZ 6, 18: services/ledger and operations)."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BusinessDay, Client, Operation, OperationEntry, User, UserStatus
from app.domain.entries import Book, ExchangeTerms, OperationType
from app.domain.errors import (
    ClientNotFound,
    ClientRequired,
    InsufficientBalance,
    NothingToExchange,
    PermissionDenied,
)
from app.services import days, exchange, ledger, loans
from tests.factories import make_client
from tests.services.accounting import (
    EUR,
    KGS,
    KZT,
    RUB,
    USD,
    D,
    adjust,
    cancel,
    force_close_day,
    loan,
    open_balance,
    settle,
    swap,
)

EXCHANGE, LOAN = Book.EXCHANGE, Book.LOAN


@pytest.fixture
async def day(session: AsyncSession) -> BusinessDay:
    return await days.ensure_open_day(session)


@pytest.fixture
async def azamat(session: AsyncSession, owner: User) -> Client:
    return await make_client(session, owner, "Азамат")


@pytest.fixture
async def bekzat(session: AsyncSession, owner: User) -> Client:
    return await make_client(session, owner, "Бекзат")


async def records(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Operation)) or 0


async def test_day_1_of_the_acceptance_scenarios(
    session: AsyncSession, day: BusinessDay, owner: User, azamat: Client, bekzat: Client
) -> None:
    # TZ 17.1, scenarios 1-5.
    await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    await swap(session, owner, "1000", USD, "87000", KGS, rate="87")
    assert (await ledger.balance(session, USD), await ledger.balance(session, KGS)) == (
        D("11000"),
        D("913000"),
    )
    await swap(session, owner, "88000", KGS, "1000", USD, rate="88")
    assert (await ledger.balance(session, USD), await ledger.balance(session, KGS)) == (
        D("10000"),
        D("1001000"),
    )
    await swap(
        session, owner, "88500", RUB, "1000", USD, rate="88.5", paid_now=False, client=azamat
    )
    await loan(session, owner, OperationType.LOAN_GIVE, bekzat, "50000")

    assert await ledger.balances(session) == {
        USD: D("10000"),
        EUR: 0,
        RUB: D("88500"),
        KZT: 0,
        KGS: D("951000"),
    }
    assert list(await ledger.balances(session)) == [USD, EUR, RUB, KZT, KGS]
    assert await ledger.client_obligations(session, azamat.id) == {(EXCHANGE, USD): D("-1000")}
    assert await ledger.client_obligations(session, bekzat.id) == {(LOAN, KGS): D("50000")}
    assert await ledger.obligation(session, azamat.id, EXCHANGE, USD) == D("-1000")
    lines = await ledger.obligation_lines(session, EXCHANGE)
    assert [(line.client, line.currency, line.amount) for line in lines] == [
        ("Азамат", USD, D("-1000"))
    ]


async def test_records_land_in_the_open_day(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    first = await open_balance(session, owner, "100", USD)
    await force_close_day(session, owner)
    second = await adjust(session, owner, "5", USD)

    assert first.day_id == day.id
    assert second.day_id == day.id + 1


async def test_books_never_net(
    session: AsyncSession, day: BusinessDay, owner: User, azamat: Client
) -> None:
    await open_balance(session, owner, "1000", USD)
    # Азамат owes 5 000 som for dollars he got, and lent us 5 000 som.
    await swap(
        session, owner, "5000", KGS, "50", USD, rate="100", received_now=False, client=azamat
    )
    await loan(session, owner, OperationType.LOAN_TAKE, azamat, "5000")

    assert await ledger.client_obligations(session, azamat.id) == {
        (EXCHANGE, KGS): D("5000"),
        (LOAN, KGS): D("-5000"),
    }


async def test_netting_inside_the_exchange_book(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    # TZ 17.1, scenarios 12-13.
    timur = await make_client(session, owner, "Тимур")
    await open_balance(session, owner, "776000", KGS)
    await swap(session, owner, "100000", RUB, "99000", RUB, paid_now=False, client=timur)
    assert await ledger.client_obligations(session, timur.id) == {(EXCHANGE, RUB): D("-99000")}

    await swap(
        session, owner, "99000", RUB, "98010", KGS, rate="0.99", received_now=False, client=timur
    )

    assert await ledger.client_obligations(session, timur.id) == {}
    assert await ledger.balance(session, KGS) == D("677990")
    assert await ledger.balance(session, RUB) == D("100000")


async def test_instant_exchange_needs_no_client(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    await open_balance(session, owner, "100000", KGS)

    record = await swap(session, owner, "100", USD, "8700", KGS, rate="87")

    assert record.client_id is None


async def test_deferred_exchange_without_client_is_refused(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    with pytest.raises(ClientRequired):
        await swap(session, owner, "100", USD, "8700", KGS, rate="87", paid_now=False)
    assert await records(session) == 0


async def test_transfers_in_one_currency(
    session: AsyncSession, day: BusinessDay, owner: User, azamat: Client
) -> None:
    await open_balance(session, owner, "1000", RUB)
    record = await swap(session, owner, "1000", RUB, "990", RUB)  # cash to an account, 1 % fee
    assert record.rate is None
    assert await ledger.balance(session, RUB) == D("1010")

    with pytest.raises(NothingToExchange):
        await swap(session, owner, "1000", RUB, "1000", RUB)
    await swap(session, owner, "1000", RUB, "1000", RUB, paid_now=False, client=azamat)
    assert await records(session) == 3


async def test_unknown_client_is_refused(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    ghost = Client(id=999, name="Призрак", created_by_id=owner.id)

    with pytest.raises(ClientNotFound):
        await loan(session, owner, OperationType.LOAN_TAKE, ghost, "1")


# --- no balance below zero (TZ 6.5) ------------------------------------------------------------
# Each case: (setup that succeeds, the action that must be refused). Start: 10 000 USD and
# 1 000 000 KGS.


async def _nothing(session: AsyncSession, owner: User, client: Client) -> object:
    return None


async def _sale_then_payout(session: AsyncSession, owner: User, client: Client) -> object:
    # The dollars of a purchase were paid out: cancelling it would take USD below zero.
    purchase = await swap(session, owner, "1000", USD, "87000", KGS, rate="87")
    await settle(session, owner, OperationType.EXCHANGE_PAYOUT, client, "10500", USD)
    return purchase


async def _exchange_paid_now(session: AsyncSession, owner: User, client: Client, _: object) -> None:
    await swap(
        session, owner, "1760000", KGS, "20000", USD, rate="88", received_now=False, client=client
    )


async def _payout(session: AsyncSession, owner: User, client: Client, _: object) -> None:
    await settle(session, owner, OperationType.EXCHANGE_PAYOUT, client, "20000", USD)


async def _loan_give(session: AsyncSession, owner: User, client: Client, _: object) -> None:
    await loan(session, owner, OperationType.LOAN_GIVE, client, "2000000")


async def _loan_repay_out(session: AsyncSession, owner: User, client: Client, _: object) -> None:
    await loan(session, owner, OperationType.LOAN_REPAY_OUT, client, "2000000")


async def _adjustment(session: AsyncSession, owner: User, client: Client, _: object) -> None:
    await adjust(session, owner, "-20000", USD)


async def _cancel_sale(session: AsyncSession, owner: User, client: Client, sale: object) -> None:
    assert isinstance(sale, Operation)
    await cancel(session, owner, sale)


@pytest.mark.parametrize(
    ("setup", "action", "currency", "available", "required"),
    [
        pytest.param(_nothing, _exchange_paid_now, USD, "10000", "20000", id="exchange"),
        pytest.param(_nothing, _payout, USD, "10000", "20000", id="payout"),
        pytest.param(_nothing, _loan_give, KGS, "1000000", "2000000", id="loan-give"),
        pytest.param(_nothing, _loan_repay_out, KGS, "1000000", "2000000", id="loan-repay-out"),
        pytest.param(_nothing, _adjustment, USD, "10000", "20000", id="adjustment"),
        pytest.param(_sale_then_payout, _cancel_sale, USD, "500", "1000", id="reversal"),
    ],
)
async def test_no_balance_goes_below_zero(
    session: AsyncSession,
    day: BusinessDay,
    owner: User,
    azamat: Client,
    setup: Any,
    action: Any,
    currency: object,
    available: str,
    required: str,
) -> None:
    await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    prepared = await setup(session, owner, azamat)
    before = await ledger.balances(session)
    count = await records(session)

    with pytest.raises(InsufficientBalance) as error:
        await action(session, owner, azamat, prepared)

    assert error.value.currency == currency
    assert (error.value.available, error.value.required) == (D(available), D(required))
    assert await ledger.balances(session) == before
    assert await records(session) == count


async def test_obligations_can_have_any_sign(
    session: AsyncSession, day: BusinessDay, owner: User, azamat: Client
) -> None:
    await open_balance(session, owner, "100", USD)
    await settle(session, owner, OperationType.EXCHANGE_PAYOUT, azamat, "100", USD)

    assert await ledger.obligation(session, azamat.id, EXCHANGE, USD) == D("100")
    assert await ledger.balance(session, USD) == 0


async def test_two_payouts_cannot_spend_the_same_money(
    sessionmaker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    day: BusinessDay,
    owner: User,
) -> None:
    # TZ 18: two exchanges paying out 60 % of the balance each; exactly one is saved.
    await open_balance(session, owner, "10000", USD)

    async def sell_dollars() -> str:
        async with sessionmaker() as own:
            terms = ExchangeTerms(KGS, D("528000"), USD, D("6000"), True, True, D("88"))
            try:
                await exchange.create_exchange(own, owner, uuid.uuid4(), terms)
            except InsufficientBalance:
                return "refused"
            return "saved"

    results = await asyncio.gather(sell_dollars(), sell_dollars())

    assert sorted(results) == ["refused", "saved"]
    assert await ledger.balance(session, USD) == D("4000")


# --- idempotency (TZ 6.7) ------------------------------------------------------------------------


async def test_repeated_request_returns_the_first_record(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    await open_balance(session, owner, "1000", USD)
    request_id = uuid.uuid4()
    terms = ExchangeTerms(USD, D("100"), KGS, D("8700"), True, True, D("87"))
    await open_balance(session, owner, "100000", KGS)

    first, created = await exchange.create_exchange(session, owner, request_id, terms)
    again, created_again = await exchange.create_exchange(session, owner, request_id, terms)

    assert (created, created_again) == (True, False)
    assert again.id == first.id
    assert await records(session) == 3


async def test_parallel_repeats_save_one_record(
    sessionmaker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    day: BusinessDay,
    owner: User,
    bekzat: Client,
) -> None:
    request_id = uuid.uuid4()

    async def save() -> tuple[int, bool]:
        async with sessionmaker() as own:
            record, created = await loans.create_loan(
                own, owner, request_id, OperationType.LOAN_TAKE, bekzat.id, D("100")
            )
            return record.id, created

    results = await asyncio.gather(*(save() for _ in range(4)))

    assert len({record_id for record_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert await session.scalar(select(func.count()).select_from(OperationEntry)) == 2


# --- rights (TZ 5) ------------------------------------------------------------------------------


async def test_helper_records_but_cannot_adjust(
    session: AsyncSession, day: BusinessDay, owner: User, helper: User, bekzat: Client
) -> None:
    record = await loan(session, helper, OperationType.LOAN_TAKE, bekzat, "100")
    assert record.author_id == helper.id

    with pytest.raises(PermissionDenied):
        await adjust(session, helper, "100", USD)


async def test_deleted_user_cannot_record(
    session: AsyncSession, day: BusinessDay, helper: User, bekzat: Client
) -> None:
    helper.status = UserStatus.DELETED
    await session.commit()

    with pytest.raises(PermissionDenied):
        await loan(session, helper, OperationType.LOAN_TAKE, bekzat, "100")
