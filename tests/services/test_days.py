"""Business days (TZ 7.1): exactly one open day, the first start opens day №1."""

import asyncio

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BusinessDay, DayStatus, User
from app.services import days


async def test_first_start_opens_day_1(session: AsyncSession) -> None:
    day = await days.ensure_open_day(session)

    assert (day.id, day.status) == (1, DayStatus.OPEN)
    assert day.opened_at is not None


async def test_open_day_is_reused(session: AsyncSession) -> None:
    first = await days.ensure_open_day(session)
    again = await days.ensure_open_day(session)

    assert again.id == first.id
    assert await days.open_day_number(session) == 1
    assert await session.scalar(select(func.count()).select_from(BusinessDay)) == 1


async def test_parallel_starts_open_one_day(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async def start() -> int:
        async with sessionmaker() as session:
            return (await days.ensure_open_day(session)).id

    assert set(await asyncio.gather(*(start() for _ in range(5)))) == {1}


async def test_a_new_day_is_opened_if_none_is_open(session: AsyncSession, owner: User) -> None:
    await days.ensure_open_day(session)
    await session.execute(
        text(
            "UPDATE business_days SET status = 'closed', closed_at = now(), closed_by_id = :owner,"
            " rates = '{}', report = '{}', surplus = 0"
        ),
        {"owner": owner.id},
    )
    await session.commit()

    assert await days.open_day_number(session) == 2
