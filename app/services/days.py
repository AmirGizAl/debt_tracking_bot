"""Business days (TZ 7): exactly one day is open, every record belongs to the open day."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BusinessDay, DayStatus


async def open_day(session: AsyncSession) -> BusinessDay | None:
    return await session.scalar(select(BusinessDay).where(BusinessDay.status == DayStatus.OPEN))


async def ensure_open_day(session: AsyncSession) -> BusinessDay:
    """The open day; the first start of the bot opens day №1 (TZ 7.1, 15.3)."""
    day = await open_day(session)
    if day is not None:
        return day
    session.add(BusinessDay(status=DayStatus.OPEN))
    try:
        await session.commit()
    except IntegrityError:
        # Another process opened it first (the partial unique index allows one open day).
        await session.rollback()
    day = await open_day(session)
    assert day is not None
    return day


async def open_day_number(session: AsyncSession) -> int:
    """ "День №N" of the menu: the id of the open day (TZ 7.1)."""
    return (await ensure_open_day(session)).id
