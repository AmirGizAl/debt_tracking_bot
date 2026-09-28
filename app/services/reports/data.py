"""Report data: database queries -> plain dataclasses (TZ 13).

Renderers in excel.py and pdf.py only turn these dataclasses into bytes.
Amounts stay Decimal; labels are ready-made Russian texts, so both formats agree.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload

from app.bot import texts
from app.db.models import CashAdjustment, Client, Operation
from app.domain.currency import CURRENCIES, HOME_CURRENCY, Currency
from app.domain.dates import format_date, last_days
from app.domain.money import format_money, quantize_money
from app.services import cash

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Period:
    """Inclusive date range; None on both ends means "всё время"."""

    start: date | None = None
    end: date | None = None

    @property
    def label(self) -> str:
        if self.start is None and self.end is None:
            return texts.REPORT_ALL_TIME
        if self.start is not None and self.start == self.end:
            return format_date(self.start)
        start = format_date(self.start) if self.start else "…"
        end = format_date(self.end) if self.end else "…"
        return f"{start} – {end}"

    @property
    def file_part(self) -> str:
        if self.start is None and self.end is None:
            return texts.REPORT_FILE_ALL_TIME
        if self.start is not None and self.start == self.end:
            return self.start.isoformat()
        start = self.start.isoformat() if self.start else texts.REPORT_FILE_OPEN_START
        end = self.end.isoformat() if self.end else texts.REPORT_FILE_OPEN_END
        return f"{start}_{end}"

    def contains(self, day: date) -> bool:
        return (self.start is None or day >= self.start) and (self.end is None or day <= self.end)

    def before(self, day: date) -> bool:
        return self.start is not None and day < self.start


class PeriodPreset(StrEnum):
    """Period buttons of the reports: the last N days up to today (agreed on 28.09.2026)."""

    TODAY = "today"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    ALL = "all"


PRESET_DAYS = {
    PeriodPreset.TODAY: 1,
    PeriodPreset.WEEK: 7,
    PeriodPreset.MONTH: 30,
    PeriodPreset.YEAR: 365,
}


def preset_period(preset: PeriodPreset, current: date) -> Period:
    """ "Неделя" on 28.09.2026 is 22.09.2026 – 28.09.2026; "Всё время" has no bounds."""
    days = PRESET_DAYS.get(preset)
    if days is None:
        return Period()
    return Period(*last_days(current, days))


@dataclass(frozen=True)
class ReportMeta:
    title: str
    generated_at: datetime  # aware, in the configured time zone
    generated_by: str
    period: Period | None = None


# --- 13.1 summary ----------------------------------------------------------------------------


@dataclass(frozen=True)
class SummaryRow:
    currency: Currency
    cash: Decimal
    owed_to_you: Decimal
    you_owe: Decimal

    @property
    def difference(self) -> Decimal:
        return self.owed_to_you - self.you_owe


@dataclass(frozen=True)
class KgsRow:
    currency: Currency
    cash: Decimal
    rate: Decimal
    kgs: Decimal


@dataclass(frozen=True)
class SummaryReport:
    meta: ReportMeta
    rows: list[SummaryRow]
    kgs_rows: list[KgsRow]

    @property
    def kgs_total(self) -> Decimal:
        # Each line is rounded to cents first, then the lines are added (TZ 13.1).
        return sum((row.kgs for row in self.kgs_rows), ZERO)


def currencies_needing_rates(cash_balances: dict[Currency, Decimal]) -> list[Currency]:
    """Currencies other than KGS with non-zero cash, in the order USD, EUR, RUB, KZT."""
    return [
        currency
        for currency in CURRENCIES
        if currency != HOME_CURRENCY and cash_balances.get(currency, ZERO) != 0
    ]


async def _client_balances(session: AsyncSession) -> list[tuple[str, Currency, Decimal]]:
    """Non-zero balance of every client in every currency."""
    rows = await session.execute(
        select(Client.name, Operation.debt_currency, func.sum(Operation.debt_delta))
        .join(Client, Client.id == Operation.client_id)
        .group_by(Client.id, Client.name, Operation.debt_currency)
    )
    return [(name, currency, total) for name, currency, total in rows if total != 0]


async def summary_data(
    session: AsyncSession, meta: ReportMeta, rates: dict[Currency, Decimal]
) -> SummaryReport:
    cash_balances = await cash.cash_balances(session)
    owed: dict[Currency, Decimal] = defaultdict(lambda: ZERO)
    owing: dict[Currency, Decimal] = defaultdict(lambda: ZERO)
    for _name, currency, balance in await _client_balances(session):
        if balance > 0:
            owed[currency] += balance
        else:
            owing[currency] += -balance
    rows = [
        SummaryRow(currency, cash_balances[currency], owed[currency], owing[currency])
        for currency in CURRENCIES
    ]
    kgs_rows = []
    for currency in CURRENCIES:
        balance = cash_balances[currency]
        if balance == 0:
            continue
        rate = Decimal(1) if currency == HOME_CURRENCY else rates[currency]
        kgs_rows.append(KgsRow(currency, balance, rate, quantize_money(balance * rate)))
    return SummaryReport(meta, rows, kgs_rows)


# --- 13.2 who owes whom ----------------------------------------------------------------------


@dataclass(frozen=True)
class DebtLine:
    client: str
    amount: Decimal


@dataclass(frozen=True)
class DebtSection:
    currency: Currency
    lines: list[DebtLine]

    @property
    def total(self) -> Decimal:
        return sum((line.amount for line in self.lines), ZERO)


@dataclass(frozen=True)
class DebtsReport:
    meta: ReportMeta
    owed_to_you: list[DebtSection]
    you_owe: list[DebtSection]


def _sections(lines: dict[Currency, list[DebtLine]]) -> list[DebtSection]:
    return [
        DebtSection(currency, sorted(lines[currency], key=lambda line: (-line.amount, line.client)))
        for currency in CURRENCIES
        if lines.get(currency)
    ]


async def debts_data(session: AsyncSession, meta: ReportMeta) -> DebtsReport:
    owed: dict[Currency, list[DebtLine]] = defaultdict(list)
    owing: dict[Currency, list[DebtLine]] = defaultdict(list)
    for name, currency, balance in await _client_balances(session):
        if balance > 0:
            owed[currency].append(DebtLine(name, balance))
        else:
            owing[currency].append(DebtLine(name, -balance))
    return DebtsReport(meta, _sections(owed), _sections(owing))


# --- 13.3 all records ------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordRow:
    number: int
    op_date: date
    operation: str
    client: str
    debt_amount: Decimal
    debt_currency: Currency
    pay_amount: Decimal | None
    pay_currency: Currency | None
    rate: str | None
    comment: str | None
    author: str
    created_at: datetime  # aware, in the report time zone
    status: str
    grey: bool


@dataclass(frozen=True)
class RecordsReport:
    meta: ReportMeta
    rows: list[RecordRow]


def _status(operation: Operation, reversed_by: int | None) -> str:
    if operation.reversal_of_id is not None:
        return texts.status_reversal_of(operation.reversal_of_id, operation.reversal_reason)
    if reversed_by is not None:
        return texts.status_cancelled_by(reversed_by)
    return ""


async def _records_in(
    session: AsyncSession, period: Period, client_id: int | None = None
) -> list[tuple[Operation, int | None]]:
    """Records with op_date in the period, by date then number, with their reversal id."""
    reversal = aliased(Operation)
    statement = (
        select(Operation, reversal.id)
        .outerjoin(reversal, reversal.reversal_of_id == Operation.id)
        .options(joinedload(Operation.client), joinedload(Operation.author))
        .order_by(Operation.op_date, Operation.id)
    )
    if period.start is not None:
        statement = statement.where(Operation.op_date >= period.start)
    if period.end is not None:
        statement = statement.where(Operation.op_date <= period.end)
    if client_id is not None:
        statement = statement.where(Operation.client_id == client_id)
    return [(operation, reversed_by) for operation, reversed_by in await session.execute(statement)]


async def records_data(session: AsyncSession, meta: ReportMeta, period: Period) -> RecordsReport:
    rows = []
    zone = meta.generated_at.tzinfo
    for operation, reversed_by in await _records_in(session, period):
        other_currency = operation.cash_currency != operation.debt_currency
        rate = None
        if other_currency:
            assert operation.rate is not None
            assert operation.rate_base is not None and operation.rate_quote is not None
            rate = texts.rate_text(operation.rate, operation.rate_base, operation.rate_quote)
        rows.append(
            RecordRow(
                number=operation.id,
                op_date=operation.op_date,
                operation=texts.TYPE_LABEL[operation.type],
                client=operation.client.name,
                debt_amount=operation.debt_amount,
                debt_currency=operation.debt_currency,
                pay_amount=operation.cash_amount if other_currency else None,
                pay_currency=operation.cash_currency if other_currency else None,
                rate=rate,
                comment=operation.comment,
                author=texts.user_name(operation.author),
                created_at=operation.created_at.astimezone(zone),
                status=_status(operation, reversed_by),
                grey=operation.reversal_of_id is not None or reversed_by is not None,
            )
        )
    return RecordsReport(meta, rows)


# --- 13.4 cash movements ---------------------------------------------------------------------


@dataclass(frozen=True)
class CashRow:
    day: date
    number: str  # record number or "корр."
    description: str
    income: Decimal | None
    expense: Decimal | None
    balance: Decimal
    grey: bool


@dataclass(frozen=True)
class CashSection:
    currency: Currency
    opening: Decimal
    rows: list[CashRow]

    @property
    def closing(self) -> Decimal:
        return self.rows[-1].balance if self.rows else self.opening


@dataclass(frozen=True)
class CashReport:
    meta: ReportMeta
    sections: list[CashSection]


@dataclass(frozen=True)
class _Move:
    day: date
    created_at: datetime
    number: str
    description: str
    amount: Decimal
    grey: bool


def _operation_label(operation: Operation) -> str:
    if operation.reversal_of_id is not None:
        return texts.reversal_label(operation.reversal_of_id)
    return texts.TYPE_LABEL[operation.type]


def _record_description(operation: Operation) -> str:
    return texts.movement_description(_operation_label(operation), operation.client.name)


async def cash_data(session: AsyncSession, meta: ReportMeta, period: Period) -> CashReport:
    opening: dict[Currency, Decimal] = defaultdict(lambda: ZERO)
    if period.start is not None:
        for currency, total in await session.execute(
            select(Operation.cash_currency, func.sum(Operation.cash_delta))
            .where(Operation.op_date < period.start)
            .group_by(Operation.cash_currency)
        ):
            opening[currency] += total
        for currency, total in await session.execute(
            select(CashAdjustment.currency, func.sum(CashAdjustment.amount))
            .where(CashAdjustment.adj_date < period.start)
            .group_by(CashAdjustment.currency)
        ):
            opening[currency] += total

    moves: dict[Currency, list[_Move]] = defaultdict(list)
    for operation, reversed_by in await _records_in(session, period):
        moves[operation.cash_currency].append(
            _Move(
                day=operation.op_date,
                created_at=operation.created_at,
                number=str(operation.id),
                description=_record_description(operation),
                amount=operation.cash_delta,
                grey=operation.reversal_of_id is not None or reversed_by is not None,
            )
        )
    statement = select(CashAdjustment)
    if period.start is not None:
        statement = statement.where(CashAdjustment.adj_date >= period.start)
    if period.end is not None:
        statement = statement.where(CashAdjustment.adj_date <= period.end)
    for adjustment in await session.scalars(statement):
        moves[adjustment.currency].append(
            _Move(
                day=adjustment.adj_date,
                created_at=adjustment.created_at,
                number=texts.REPORT_ADJUSTMENT_NUMBER,
                description=texts.movement_description(texts.ADJUSTMENT_LABEL, adjustment.reason),
                amount=adjustment.amount,
                grey=False,
            )
        )

    sections = []
    for currency in CURRENCIES:
        currency_moves = sorted(moves[currency], key=lambda move: (move.day, move.created_at))
        if not currency_moves and opening[currency] == 0:
            continue
        balance = opening[currency]
        rows = []
        for move in currency_moves:
            balance += move.amount
            rows.append(
                CashRow(
                    day=move.day,
                    number=move.number,
                    description=move.description,
                    income=move.amount if move.amount > 0 else None,
                    expense=-move.amount if move.amount < 0 else None,
                    balance=balance,
                    grey=move.grey,
                )
            )
        sections.append(CashSection(currency, opening[currency], rows))
    return CashReport(meta, sections)


# --- 13.5 client statement -------------------------------------------------------------------


@dataclass(frozen=True)
class StatementRow:
    op_date: date
    number: int
    operation: str
    change: Decimal  # signed: plus means the client owes more
    payment: str | None
    balance: Decimal
    grey: bool


@dataclass(frozen=True)
class StatementSection:
    currency: Currency
    opening: Decimal
    rows: list[StatementRow]

    @property
    def closing(self) -> Decimal:
        return self.rows[-1].balance if self.rows else self.opening


@dataclass(frozen=True)
class StatementReport:
    meta: ReportMeta
    client: str
    sections: list[StatementSection]


balance_phrase = texts.balance_phrase


async def statement_data(
    session: AsyncSession, meta: ReportMeta, period: Period, client_id: int
) -> StatementReport:
    client = await session.get(Client, client_id)
    assert client is not None
    everything_until_end = Period(None, period.end)
    opening: dict[Currency, Decimal] = defaultdict(lambda: ZERO)
    rows: dict[Currency, list[StatementRow]] = defaultdict(list)
    seen: set[Currency] = set()
    for operation, reversed_by in await _records_in(session, everything_until_end, client_id):
        currency = operation.debt_currency
        seen.add(currency)
        if period.before(operation.op_date):
            opening[currency] += operation.debt_delta
            continue
        previous = rows[currency][-1].balance if rows[currency] else opening[currency]
        payment = None
        if operation.cash_currency != currency:
            assert operation.rate is not None
            assert operation.rate_base is not None and operation.rate_quote is not None
            payment = texts.statement_payment(
                format_money(operation.cash_amount, operation.cash_currency),
                texts.rate_text(operation.rate, operation.rate_base, operation.rate_quote),
            )
        rows[currency].append(
            StatementRow(
                op_date=operation.op_date,
                number=operation.id,
                operation=_operation_label(operation),
                change=operation.debt_delta,
                payment=payment,
                balance=previous + operation.debt_delta,
                grey=operation.reversal_of_id is not None or reversed_by is not None,
            )
        )
    sections = [
        StatementSection(currency, opening[currency], rows[currency])
        for currency in CURRENCIES
        if currency in seen
    ]
    return StatementReport(meta, client.name, sections)
