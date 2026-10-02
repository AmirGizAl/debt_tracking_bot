"""Opening balances (TZ 9, 18: «Начальные балансы»)."""

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BusinessDay, User
from app.domain.errors import BaselineFrozen, OpeningExists, PermissionDenied
from app.services import days, ledger, opening
from tests.services.accounting import (
    EUR,
    KGS,
    KZT,
    RUB,
    USD,
    D,
    cancel,
    force_close_day,
    open_balance,
)


@pytest.fixture
async def day(session: AsyncSession) -> BusinessDay:
    return await days.ensure_open_day(session)


async def test_baseline_counts_cancellations(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    wrong = await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    await cancel(session, owner, wrong, "ошибка")
    await open_balance(session, owner, "12000", USD)

    assert await opening.baseline(session) == {
        USD: D("12000"),
        EUR: 0,
        RUB: 0,
        KZT: 0,
        KGS: D("1000000"),
    }
    assert await ledger.balance(session, USD) == D("12000")


async def test_one_opening_per_currency(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    first = await open_balance(session, owner, "10000", USD)

    with pytest.raises(OpeningExists) as error:
        await open_balance(session, owner, "500", USD)
    assert error.value.currency == USD
    await open_balance(session, owner, "500", EUR)  # other currencies are free

    await cancel(session, owner, first)
    await open_balance(session, owner, "500", USD)  # after the cancellation it is free again


async def test_parallel_openings_of_a_currency_save_one(
    sessionmaker: async_sessionmaker[AsyncSession], day: BusinessDay, owner: User
) -> None:
    async def enter(amount: str) -> str:
        async with sessionmaker() as own:
            try:
                await opening.create_opening(own, owner, uuid.uuid4(), USD, D(amount))
            except OpeningExists:
                return "refused"
            return "saved"

    assert sorted(await asyncio.gather(enter("100"), enter("200"))) == ["refused", "saved"]


async def test_baseline_freezes_after_the_first_closing(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    usd = await open_balance(session, owner, "10000", USD)
    assert not await opening.baseline_frozen(session)

    await force_close_day(session, owner)

    assert await opening.baseline_frozen(session)
    with pytest.raises(BaselineFrozen):
        await open_balance(session, owner, "1000", EUR)
    with pytest.raises(BaselineFrozen):
        await cancel(session, owner, usd)
    assert await opening.baseline(session) == {
        USD: D("10000"),
        EUR: 0,
        RUB: 0,
        KZT: 0,
        KGS: 0,
    }


async def test_helper_cannot_enter_opening_balances(
    session: AsyncSession, day: BusinessDay, helper: User
) -> None:
    with pytest.raises(PermissionDenied):
        await open_balance(session, helper, "100", USD)


async def test_repeated_request_returns_the_same_opening(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    request_id = uuid.uuid4()
    first, _ = await opening.create_opening(session, owner, request_id, USD, D("100"))

    again, created = await opening.create_opening(session, owner, request_id, USD, D("100"))

    assert (again.id, created) == (first.id, False)  # not OpeningExists
