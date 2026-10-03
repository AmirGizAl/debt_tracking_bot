"""Report data: database queries -> plain dataclasses (TZ 8.4, 14).

Renderers in excel.py and pdf.py only turn these dataclasses into bytes.
Amounts stay Decimal; labels are ready-made Russian texts, so both formats agree.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.bot import texts
from app.db.models import Client, Operation, OperationEntry, User
from app.domain.currency import CURRENCIES, HOME_CURRENCY, Currency
from app.domain.dates import day_bounds
from app.domain.day_report import DayReport, ExchangeList, NameLine
from app.domain.entries import Book, EntryKind, OperationType
from app.services import ledger
from app.services.ledger import ObligationLine

ZERO = Decimal("0.00")


class ReportFormat(StrEnum):
    XLSX = "xlsx"
    PDF = "pdf"


@dataclass(frozen=True)
class ReportMeta:
    title: str
    generated_at: datetime  # aware, in the configured time zone
    generated_by: str
    scope: str | None = None  # "Закрыл: …" or a period of dates, ready to print


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: Currency


@dataclass(frozen=True)
class JournalRow:
    """A record in the columns of TZ 14.3; cancelled records and cancellations are grey."""

    number: int
    day: int
    time: datetime  # aware, in the configured time zone
    type_label: str
    client: str
    gives: Money | None  # an exchange: what the client gives
    gets: Money | None  # an exchange: what the client gets
    rate: str
    execution: str
    amount: Money | None  # every other type; an adjustment has a sign
    note: str  # the comment, or the reason of an adjustment
    author: str
    status: str
    grey: bool


@dataclass(frozen=True)
class DayReportData:
    """The file of a day report (TZ 8.4): a closed day from its snapshot, or the open day."""

    meta: ReportMeta
    report: DayReport
    records: list[JournalRow]


def _journal_row(
    operation: Operation,
    client: str | None,
    author: User,
    reversed_by: int | None,
    zone: ZoneInfo,
) -> JournalRow:
    gives = gets = amount = None
    rate = execution = ""
    if operation.type == OperationType.EXCHANGE:
        assert operation.give_amount is not None and operation.give_currency is not None
        assert operation.get_amount is not None and operation.get_currency is not None
        assert operation.received_now is not None and operation.paid_now is not None
        gives = Money(operation.give_amount, operation.give_currency)
        gets = Money(operation.get_amount, operation.get_currency)
        if operation.rate is not None:
            assert operation.rate_base is not None and operation.rate_quote is not None
            rate = texts.rate_text(operation.rate, operation.rate_base, operation.rate_quote)
        execution = texts.EXECUTION[operation.received_now, operation.paid_now]
        client = client or texts.NO_CLIENT
    else:
        assert operation.amount is not None and operation.currency is not None
        amount = Money(operation.amount, operation.currency)
    return JournalRow(
        number=operation.id,
        day=operation.day_id,
        time=operation.created_at.astimezone(zone),
        type_label=texts.TYPE_LABEL[operation.type],
        client=client or "",
        gives=gives,
        gets=gets,
        rate=rate,
        execution=execution,
        amount=amount,
        note=operation.comment or operation.reason or "",
        author=texts.user_name(author),
        status=texts.journal_status(
            reversed_by, operation.reversal_of_id, operation.reversal_reason
        ),
        grey=reversed_by is not None or operation.reversal_of_id is not None,
    )


async def journal_rows(
    session: AsyncSession, zone: ZoneInfo, *conditions: ColumnElement[Any]
) -> list[JournalRow]:
    """Records matching `conditions`, the oldest first."""
    reversal = aliased(Operation)
    rows = await session.execute(
        select(Operation, Client.name, User, reversal.id)
        .outerjoin(Client, Client.id == Operation.client_id)
        .join(User, User.id == Operation.author_id)
        .outerjoin(reversal, reversal.reversal_of_id == Operation.id)
        .where(*conditions)
        .order_by(Operation.id)
    )
    return [
        _journal_row(operation, client, author, reversed_by, zone)
        for operation, client, author, reversed_by in rows
    ]


# --- periods (TZ 13.10) --------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    """A business day, an inclusive range of dates in TZ, or all time (nothing set)."""

    day_id: int | None = None
    start: date | None = None
    end: date | None = None

    def records(self, zone: ZoneInfo) -> list[ColumnElement[bool]]:
        """Conditions on `operations` for the records of the period."""
        if self.day_id is not None:
            return [Operation.day_id == self.day_id]
        if self.start is not None and self.end is not None:
            low, high = day_bounds(self.start, self.end, zone)
            return [Operation.created_at >= low, Operation.created_at < high]
        return []

    def earlier(self, zone: ZoneInfo) -> list[ColumnElement[bool]] | None:
        """Conditions for the records before the period; None when nothing is before it."""
        if self.day_id is not None:
            return [Operation.day_id < self.day_id]
        if self.start is not None:
            low, _ = day_bounds(self.start, self.start, zone)
            return [Operation.created_at < low]
        return None


@dataclass(frozen=True)
class Record:
    """A record of a period with its entries, the client's name and its cancellation."""

    operation: Operation
    client: str | None
    reversed_by: int | None

    @property
    def grey(self) -> bool:
        return self.reversed_by is not None or self.operation.reversal_of_id is not None


async def _records(session: AsyncSession, *conditions: ColumnElement[bool]) -> list[Record]:
    reversal = aliased(Operation)
    rows = await session.execute(
        select(Operation, Client.name, reversal.id)
        .outerjoin(Client, Client.id == Operation.client_id)
        .outerjoin(reversal, reversal.reversal_of_id == Operation.id)
        .where(*conditions)
        .options(selectinload(Operation.entries))
        .order_by(Operation.created_at, Operation.id)
    )
    return [Record(operation, client, reversed_by) for operation, client, reversed_by in rows]


async def _sums_before(
    session: AsyncSession, earlier: list[ColumnElement[bool]] | None, *where: ColumnElement[bool]
) -> dict[tuple[Any, ...], Decimal]:
    """Sums of entries before the period, by (book, currency)."""
    if earlier is None:
        return {}
    rows = await session.execute(
        select(OperationEntry.book, OperationEntry.currency, func.sum(OperationEntry.delta))
        .join(Operation, Operation.id == OperationEntry.operation_id)
        .where(*where, *earlier)
        .group_by(OperationEntry.book, OperationEntry.currency)
    )
    return {(book, currency): total for book, currency, total in rows}


# --- «Кто кому должен» (TZ 14.2) -----------------------------------------------------------------


@dataclass(frozen=True)
class WhoOwesData:
    meta: ReportMeta
    exchanges: list[ExchangeList]  # every currency with obligations
    loans: ExchangeList  # som loans


def _by_currency(lines: list[ObligationLine]) -> list[ExchangeList]:
    result = []
    for currency in CURRENCIES:
        items = [line for line in lines if line.currency == currency]
        owed = [NameLine(line.client, line.amount) for line in items if line.amount > 0]
        owing = [NameLine(line.client, -line.amount) for line in items if line.amount < 0]
        if owed or owing:
            result.append(
                ExchangeList(
                    currency,
                    sorted(owed, key=lambda line: (-line.amount, line.name)),
                    sorted(owing, key=lambda line: (-line.amount, line.name)),
                )
            )
    return result


async def who_owes_data(session: AsyncSession, meta: ReportMeta) -> WhoOwesData:
    exchanges = _by_currency(await ledger.obligation_lines(session, Book.EXCHANGE))
    loans = _by_currency(await ledger.obligation_lines(session, Book.LOAN))
    return WhoOwesData(meta, exchanges, loans[0] if loans else ExchangeList(HOME_CURRENCY, [], []))


# --- «Журнал записей» (TZ 14.3) ------------------------------------------------------------------


@dataclass(frozen=True)
class JournalData:
    meta: ReportMeta
    records: list[JournalRow]


async def journal_data(
    session: AsyncSession, meta: ReportMeta, period: Period, zone: ZoneInfo
) -> JournalData:
    return JournalData(meta, await journal_rows(session, zone, *period.records(zone)))


# --- «Движение балансов» (TZ 14.4) ---------------------------------------------------------------


@dataclass(frozen=True)
class MovementRow:
    time: datetime
    number: int
    description: str
    incoming: Decimal | None
    outgoing: Decimal | None
    balance: Decimal
    grey: bool


@dataclass(frozen=True)
class MovementBlock:
    currency: Currency
    start: Decimal
    rows: list[MovementRow]
    end: Decimal


@dataclass(frozen=True)
class MovementData:
    meta: ReportMeta
    blocks: list[MovementBlock]


async def movement_data(
    session: AsyncSession, meta: ReportMeta, period: Period, zone: ZoneInfo
) -> MovementData:
    """Every balance that moved in the period or is not zero: the start, the moves, the end."""
    starts = await _sums_before(
        session, period.earlier(zone), OperationEntry.kind == EntryKind.CASH
    )
    records = await _records(session, *period.records(zone))
    blocks = []
    for currency in CURRENCIES:
        start = balance = starts.get((None, currency), ZERO)
        rows = []
        for record in records:
            deltas = [
                entry.delta
                for entry in record.operation.entries
                if entry.kind == EntryKind.CASH and entry.currency == currency
            ]
            if not deltas:
                continue
            incoming = sum((delta for delta in deltas if delta > 0), ZERO)
            outgoing = -sum((delta for delta in deltas if delta < 0), ZERO)
            balance += incoming - outgoing
            rows.append(
                MovementRow(
                    time=record.operation.created_at.astimezone(zone),
                    number=record.operation.id,
                    description=texts.record_line(
                        record.operation, record.client, record.reversed_by
                    ),
                    incoming=incoming or None,
                    outgoing=outgoing or None,
                    balance=balance,
                    grey=record.grey,
                )
            )
        if rows or start != 0:
            blocks.append(MovementBlock(currency, start, rows, balance))
    return MovementData(meta, blocks)


# --- «Выписка по клиенту» (TZ 14.5) --------------------------------------------------------------


@dataclass(frozen=True)
class StatementRow:
    time: datetime
    number: int
    operation: str
    change: Decimal  # above zero: the client owes more
    after: Decimal  # the obligation after the record: above zero the client owes us
    grey: bool


@dataclass(frozen=True)
class StatementBlock:
    book: Book
    currency: Currency
    start: Decimal
    rows: list[StatementRow]
    end: Decimal


@dataclass(frozen=True)
class StatementData:
    meta: ReportMeta
    client: str
    blocks: list[StatementBlock]


async def statement_data(
    session: AsyncSession, meta: ReportMeta, period: Period, zone: ZoneInfo, client: Client
) -> StatementData:
    """A block for every book and currency where the client had records or owes something."""
    starts = await _sums_before(
        session,
        period.earlier(zone),
        OperationEntry.kind == EntryKind.OBLIGATION,
        OperationEntry.client_id == client.id,
    )
    records = await _records(session, *period.records(zone), Operation.client_id == client.id)
    blocks = []
    for book in Book:
        for currency in CURRENCIES:
            start = value = starts.get((book, currency), ZERO)
            rows = []
            for record in records:
                entries = [
                    entry
                    for entry in record.operation.entries
                    if entry.kind == EntryKind.OBLIGATION
                    and entry.book == book
                    and entry.currency == currency
                    and entry.client_id == client.id
                ]
                if not entries:
                    continue
                change = sum((entry.delta for entry in entries), ZERO)
                value += change
                rows.append(
                    StatementRow(
                        time=record.operation.created_at.astimezone(zone),
                        number=record.operation.id,
                        operation=texts.record_line(
                            record.operation, None, record.reversed_by, with_client=False
                        ),
                        change=change,
                        after=value,
                        grey=record.grey,
                    )
                )
            if rows or start != 0:
                blocks.append(StatementBlock(book, currency, start, rows, value))
    return StatementData(meta, client.name, blocks)
