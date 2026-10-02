"""Cancellation of records (TZ 11, 18: «Отмена»)."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BusinessDay, Client, Operation, OperationEntry, User
from app.domain.entries import Book, OperationType
from app.domain.errors import (
    AlreadyReversed,
    CannotReverse,
    CannotReverseReason,
    EmptyText,
    InsufficientBalance,
    PermissionDenied,
)
from app.services import days, ledger, reversal
from tests.factories import make_client
from tests.services.accounting import (
    KGS,
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


@pytest.fixture
async def day(session: AsyncSession) -> BusinessDay:
    return await days.ensure_open_day(session)


@pytest.fixture
async def azamat(session: AsyncSession, owner: User) -> Client:
    return await make_client(session, owner, "Азамат")


@pytest.fixture
async def funded(session: AsyncSession, day: BusinessDay, owner: User) -> User:
    await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    return owner


async def entry_sums(
    session: AsyncSession, *records: Operation
) -> dict[tuple[object, ...], Decimal]:
    rows = await session.execute(
        select(
            OperationEntry.kind,
            OperationEntry.book,
            OperationEntry.client_id,
            OperationEntry.currency,
            func.sum(OperationEntry.delta),
        )
        .where(OperationEntry.operation_id.in_([record.id for record in records]))
        .group_by(
            OperationEntry.kind,
            OperationEntry.book,
            OperationEntry.client_id,
            OperationEntry.currency,
        )
    )
    return {tuple(row[:4]): row[4] for row in rows}


async def _deferred_exchange(session: AsyncSession, owner: User, client: Client) -> Operation:
    return await swap(
        session, owner, "88500", RUB, "1000", USD, rate="88.5", paid_now=False, client=client
    )


async def _payout(session: AsyncSession, owner: User, client: Client) -> Operation:
    return await settle(session, owner, OperationType.EXCHANGE_PAYOUT, client, "1000", USD)


async def _loan(session: AsyncSession, owner: User, client: Client) -> Operation:
    return await loan(session, owner, OperationType.LOAN_GIVE, client, "50000")


async def _opening(session: AsyncSession, owner: User, client: Client) -> Operation:
    return await open_balance(session, owner, "5000", RUB)


@pytest.mark.parametrize("make", [_deferred_exchange, _payout, _loan, _opening])
async def test_cancellation_mirrors_every_entry(
    session: AsyncSession, funded: User, azamat: Client, make: object
) -> None:
    original = await make(session, funded, azamat)  # type: ignore[operator]

    mirror = await cancel(session, funded, original, "ошибка в сумме")

    assert set((await entry_sums(session, original, mirror)).values()) == {0}
    assert (mirror.type, mirror.reversal_of_id, mirror.reversal_reason) == (
        original.type,
        original.id,
        "ошибка в сумме",
    )
    assert (mirror.amount, mirror.give_amount, mirror.client_id) == (
        original.amount,
        original.give_amount,
        original.client_id,
    )
    assert mirror.comment is None


async def test_only_the_author_cancels(
    session: AsyncSession, funded: User, helper: User, azamat: Client
) -> None:
    by_helper = await loan(session, helper, OperationType.LOAN_TAKE, azamat, "100")
    by_owner = await loan(session, funded, OperationType.LOAN_TAKE, azamat, "100")

    with pytest.raises(PermissionDenied):
        await cancel(session, funded, by_helper)  # not even the owner
    with pytest.raises(PermissionDenied):
        await cancel(session, helper, by_owner)
    await cancel(session, helper, by_helper)


async def test_a_record_is_cancelled_once(
    session: AsyncSession, funded: User, azamat: Client
) -> None:
    record = await loan(session, funded, OperationType.LOAN_TAKE, azamat, "100")
    await cancel(session, funded, record)

    with pytest.raises(AlreadyReversed):
        await cancel(session, funded, record)


async def test_parallel_cancellations_save_one(
    sessionmaker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    funded: User,
    azamat: Client,
) -> None:
    record = await loan(session, funded, OperationType.LOAN_TAKE, azamat, "100")

    async def try_cancel() -> str:
        async with sessionmaker() as own:
            try:
                await reversal.reverse(own, funded, uuid.uuid4(), record.id, "дубль")
            except AlreadyReversed:
                return "refused"
            return "cancelled"

    assert sorted(await asyncio.gather(try_cancel(), try_cancel())) == ["cancelled", "refused"]


async def test_cancellation_and_adjustment_cannot_be_cancelled(
    session: AsyncSession, funded: User, azamat: Client
) -> None:
    record = await loan(session, funded, OperationType.LOAN_TAKE, azamat, "100")
    mirror = await cancel(session, funded, record)
    adjustment = await adjust(session, funded, "100", USD)

    with pytest.raises(CannotReverse) as error:
        await cancel(session, funded, mirror)
    assert error.value.reason == CannotReverseReason.REVERSAL
    with pytest.raises(CannotReverse) as error:
        await cancel(session, funded, adjustment)
    assert error.value.reason == CannotReverseReason.ADJUSTMENT


async def test_reason_is_required(session: AsyncSession, funded: User, azamat: Client) -> None:
    record = await loan(session, funded, OperationType.LOAN_TAKE, azamat, "100")

    with pytest.raises(EmptyText):
        await cancel(session, funded, record, "   ")


async def test_cancellation_needs_the_money(
    session: AsyncSession, funded: User, azamat: Client
) -> None:
    taken = await loan(session, funded, OperationType.LOAN_TAKE, azamat, "100000")
    await loan(session, funded, OperationType.LOAN_GIVE, azamat, "1050000")

    with pytest.raises(InsufficientBalance) as error:
        await cancel(session, funded, taken)
    assert (error.value.currency, error.value.available, error.value.required) == (
        KGS,
        D("50000"),
        D("100000"),
    )
    assert await ledger.reversal_of(session, taken.id) is None


async def test_cancellation_lands_in_the_open_day(
    session: AsyncSession, funded: User, azamat: Client, day: BusinessDay
) -> None:
    record = await loan(session, funded, OperationType.LOAN_GIVE, azamat, "50000")
    await force_close_day(session, funded)

    mirror = await cancel(session, funded, record)

    assert record.day_id == day.id
    assert mirror.day_id == day.id + 1
    assert await ledger.obligation(session, azamat.id, Book.LOAN, KGS) == 0


async def test_can_reverse_decides_the_button(
    session: AsyncSession, funded: User, helper: User, azamat: Client
) -> None:
    record = await loan(session, funded, OperationType.LOAN_TAKE, azamat, "100")
    adjustment = await adjust(session, funded, "100", USD)
    opening_record = await open_balance(session, funded, "1", RUB)

    assert reversal.can_reverse(funded, record, None, frozen=False)
    assert not reversal.can_reverse(helper, record, None, frozen=False)
    assert not reversal.can_reverse(funded, adjustment, None, frozen=False)
    assert reversal.can_reverse(funded, opening_record, None, frozen=False)
    assert not reversal.can_reverse(funded, opening_record, None, frozen=True)
    mirror = await cancel(session, funded, record)
    assert not reversal.can_reverse(funded, record, mirror, frozen=False)
    assert not reversal.can_reverse(funded, mirror, None, frozen=False)
