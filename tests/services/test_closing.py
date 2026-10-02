"""Preliminary report, closing, archive (TZ 7, 8; 18: «Рабочие дни»)."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BusinessDay, Client, DayStatus, Operation, User
from app.domain.entries import OperationType
from app.domain.errors import DayAlreadyClosed, MissingRate, PermissionDenied
from app.services import adjustments, days
from tests.factories import make_client
from tests.services.accounting import KGS, RUB, USD, D, loan, open_balance, settle, swap

DAY_1_RATES = {USD: D("87.65"), RUB: D("0.991")}
DAY_2_RATES = {USD: D("87.70"), RUB: D("0.99")}


@pytest.fixture
async def day(session: AsyncSession) -> BusinessDay:
    return await days.ensure_open_day(session)


@pytest.fixture
async def azamat(session: AsyncSession, owner: User) -> Client:
    return await make_client(session, owner, "Азамат")


async def day_1(session: AsyncSession, owner: User, azamat: Client) -> None:
    """TZ 17.1, scenarios 1-5."""
    bekzat = await make_client(session, owner, "Бекзат")
    await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    await swap(session, owner, "1000", USD, "87000", KGS, rate="87")
    await swap(session, owner, "88000", KGS, "1000", USD, rate="88")
    await swap(
        session, owner, "88500", RUB, "1000", USD, rate="88.5", paid_now=False, client=azamat
    )
    await loan(session, owner, OperationType.LOAN_GIVE, bekzat, "50000")


async def test_preliminary_report_saves_nothing(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    # TZ 17.1, scenario 1.
    await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    assert await days.rates_to_ask(session) == [USD]

    open_day, report = await days.preliminary_report(session, {USD: D("87.65")})

    assert open_day.id == day.id
    assert (report.total, report.baseline_total, report.surplus) == (
        D("1876500"),
        D("1876500"),
        0,
    )
    await session.refresh(day)
    assert day.status == DayStatus.OPEN


async def test_closing_saves_the_day_and_opens_the_next(
    session: AsyncSession, day: BusinessDay, owner: User, azamat: Client
) -> None:
    await day_1(session, owner, azamat)
    _, preliminary = await days.preliminary_report(session, DAY_1_RATES)
    assert preliminary.surplus == D("1053.50")  # TZ 17.1, scenario 7

    closed = await days.close_day(session, owner, day.id, DAY_1_RATES)

    assert closed.report.surplus == D("1053.50")
    assert closed.report.change == D("1053.50")
    assert closed.next_day_id == day.id + 1
    stored = await session.get(BusinessDay, day.id, populate_existing=True)
    assert stored is not None
    assert (stored.status, stored.closed_by_id, stored.surplus) == (
        DayStatus.CLOSED,
        owner.id,
        D("1053.50"),
    )
    assert stored.closed_at is not None
    assert stored.rates == {"USD": "87.65", "RUB": "0.991"}
    assert stored.report is not None
    assert stored.report["surplus"] == "1053.50"
    assert (await days.ensure_open_day(session)).id == closed.next_day_id
    assert await days.last_rates(session) == DAY_1_RATES


async def test_two_days_of_the_acceptance_scenarios(
    session: AsyncSession, day: BusinessDay, owner: User, azamat: Client
) -> None:
    await day_1(session, owner, azamat)
    await days.close_day(session, owner, day.id, DAY_1_RATES)
    # TZ 17.1, scenarios 9-11.
    await settle(session, owner, OperationType.EXCHANGE_PAYOUT, azamat, "1000", USD)
    await swap(session, owner, "2000", USD, "175000", KGS, rate="87.5")

    closed = await days.close_day(session, owner, day.id + 1, DAY_2_RATES)

    report = closed.report
    assert (report.total, report.baseline_total, report.surplus, report.change) == (
        D("1878315"),
        D("1877000"),
        D("1315"),
        D("261.50"),
    )
    archived_day, archived = await days.archived_report(session, day.id)
    assert archived.surplus == D("1053.50")  # the snapshot of day 1 has not changed
    assert archived_day.id == day.id
    page = await days.closed_days(session, 0)
    assert [closed_day.id for closed_day in page.items] == [day.id + 1, day.id]


async def test_helper_cannot_close_the_day(
    session: AsyncSession, day: BusinessDay, helper: User
) -> None:
    with pytest.raises(PermissionDenied):
        await days.close_day(session, helper, day.id, {})


async def test_a_day_is_closed_once(session: AsyncSession, day: BusinessDay, owner: User) -> None:
    await days.close_day(session, owner, day.id, {})

    with pytest.raises(DayAlreadyClosed):
        await days.close_day(session, owner, day.id, {})
    assert (
        await session.scalar(
            select(func.count()).select_from(BusinessDay).where(BusinessDay.status == "open")
        )
        == 1
    )


async def test_parallel_closings_close_once(
    sessionmaker: async_sessionmaker[AsyncSession], day: BusinessDay, owner: User
) -> None:
    async def close() -> str:
        async with sessionmaker() as own:
            try:
                await days.close_day(own, owner, day.id, {})
            except DayAlreadyClosed:
                return "refused"
            return "closed"

    assert sorted(await asyncio.gather(close(), close())) == ["closed", "refused"]


async def test_closing_needs_every_rate(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    await open_balance(session, owner, "100", USD)

    with pytest.raises(MissingRate):
        await days.close_day(session, owner, day.id, {})
    await session.refresh(day)
    assert day.status == DayStatus.OPEN


async def test_records_after_closing_go_to_the_next_day(
    session: AsyncSession, day: BusinessDay, owner: User, azamat: Client
) -> None:
    closed = await days.close_day(session, owner, day.id, {})

    record = await loan(session, owner, OperationType.LOAN_TAKE, azamat, "100")

    assert record.day_id == closed.next_day_id


async def test_closing_and_a_record_in_parallel_lose_nothing(
    sessionmaker: async_sessionmaker[AsyncSession], session: AsyncSession, owner: User
) -> None:
    # TZ 18: the record ends up either in the closed day and its snapshot, or in the next day.
    for _ in range(8):
        day_id = (await days.ensure_open_day(session)).id

        async def close(day_id: int = day_id) -> days.ClosedDay:
            async with sessionmaker() as own:
                return await days.close_day(own, owner, day_id, {USD: D("90")})

        async def add() -> Operation:
            async with sessionmaker() as own:
                record, _ = await adjustments.create_adjustment(
                    own, owner, uuid.uuid4(), USD, D("100"), "излишек"
                )
                return record

        closed, record = await asyncio.gather(close(), add())

        in_closed_day = await session.scalar(
            select(func.count()).select_from(Operation).where(Operation.day_id <= closed.day.id)
        )
        usd = next(line for line in closed.report.lines if line.currency == USD)
        assert usd.cash == D("100") * in_closed_day  # the snapshot counts exactly those
        assert record.day_id in (closed.day.id, closed.next_day_id)
