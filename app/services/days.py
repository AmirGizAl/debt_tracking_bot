"""Business days (TZ 7, 8): exactly one day is open, every record belongs to the open day.

Closing takes the open day FOR UPDATE: it waits for the records being written (they hold the
day FOR SHARE), and new records wait for the closing, then land in the next day.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BusinessDay, DayStatus, User
from app.domain.currency import Currency
from app.domain.day_report import (
    DayReport,
    Obligation,
    ReportInputs,
    build_day_report,
    needed_rates,
    report_from_json,
    report_to_json,
)
from app.domain.entries import Book
from app.domain.errors import DayAlreadyClosed, DayNotFound
from app.services import ledger, opening, opening_debts
from app.services.pagination import Page, paginate
from app.services.transactions import isolated
from app.services.users import require_owner

ZERO = Decimal("0.00")


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


# --- the report ---------------------------------------------------------------------------------


async def report_inputs(session: AsyncSession) -> ReportInputs:
    """Balances, obligations of both books, opening balances and opening debts right now."""

    async def book(name: Book) -> list[Obligation]:
        return [
            Obligation(line.client, line.currency, line.amount)
            for line in await ledger.obligation_lines(session, name)
        ]

    return ReportInputs(
        cash=await ledger.balances(session),
        exchange=await book(Book.EXCHANGE),
        loans=await book(Book.LOAN),
        baseline=await opening.baseline(session),
        debts=await opening_debts.debt_baseline(session),
    )


async def rates_to_ask(session: AsyncSession) -> list[Currency]:
    """TZ 8.2: currencies with a position or an opening balance, in display order."""
    return needed_rates(await report_inputs(session))


async def last_rates(session: AsyncSession) -> dict[Currency, Decimal]:
    """Rates of the last closed day, for the «Как в прошлый раз» buttons (TZ 8.2)."""
    rates = await session.scalar(
        select(BusinessDay.rates)
        .where(BusinessDay.status == DayStatus.CLOSED)
        .order_by(BusinessDay.id.desc())
        .limit(1)
    )
    return {Currency(code): Decimal(value) for code, value in (rates or {}).items()}


async def previous_surplus(session: AsyncSession, day_id: int) -> Decimal:
    """Surplus of the last day closed before `day_id`; 0 for the first day (TZ 8.1)."""
    surplus = await session.scalar(
        select(BusinessDay.surplus)
        .where(BusinessDay.status == DayStatus.CLOSED, BusinessDay.id < day_id)
        .order_by(BusinessDay.id.desc())
        .limit(1)
    )
    return surplus if surplus is not None else ZERO


async def preliminary_report(
    session: AsyncSession, rates: dict[Currency, Decimal]
) -> tuple[BusinessDay, DayReport]:
    """TZ 8.3: the open day right now; nothing is saved."""
    day = await ensure_open_day(session)
    previous = await previous_surplus(session, day.id)
    return day, build_day_report(await report_inputs(session), rates, previous)


@dataclass(frozen=True)
class ClosedDay:
    day: BusinessDay
    report: DayReport
    next_day_id: int


async def close_day(
    session: AsyncSession, actor: User, day_id: int, rates: dict[Currency, Decimal]
) -> ClosedDay:
    """TZ 7.2: owners only; raises DayAlreadyClosed if somebody closed it first."""
    require_owner(actor)
    async with isolated(session) as tx:
        day = await tx.scalar(select(BusinessDay).where(BusinessDay.id == day_id).with_for_update())
        if day is None:
            raise DayNotFound(day_id)
        if day.status == DayStatus.CLOSED:
            raise DayAlreadyClosed(day_id)
        # After the lock every record of this day is committed and seen by these queries.
        report = build_day_report(
            await report_inputs(tx), rates, await previous_surplus(tx, day.id)
        )
        day.status = DayStatus.CLOSED
        day.closed_at = datetime.now(UTC)
        day.closed_by_id = actor.id
        day.rates = {str(currency): str(rate) for currency, rate in report.rates.items()}
        day.report = report_to_json(report)
        day.surplus = report.surplus
        await tx.flush()
        next_day = BusinessDay(status=DayStatus.OPEN)
        tx.add(next_day)
        await tx.flush()
        next_day_id = next_day.id
    return ClosedDay(day, report, next_day_id)


# --- the archive (TZ 8.5) ------------------------------------------------------------------------


async def closed_days(session: AsyncSession, page: int) -> Page[BusinessDay]:
    """Closed days, the newest first."""
    statement = (
        select(BusinessDay)
        .where(BusinessDay.status == DayStatus.CLOSED)
        .order_by(BusinessDay.id.desc())
    )
    return await paginate(session, statement, page)


async def archived_report(session: AsyncSession, day_id: int) -> tuple[BusinessDay, DayReport]:
    """The snapshot of a closed day: never recalculated, so it never changes."""
    # Fresh from the database: the day may have been closed by another transaction.
    day = await session.get(BusinessDay, day_id, populate_existing=True)
    if day is None or day.status != DayStatus.CLOSED or day.report is None:
        raise DayNotFound(day_id)
    return day, report_from_json(day.report)
