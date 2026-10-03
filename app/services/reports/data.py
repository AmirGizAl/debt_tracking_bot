"""Report data: database queries -> plain dataclasses (TZ 8.4, 14).

Renderers in excel.py and pdf.py only turn these dataclasses into bytes.
Amounts stay Decimal; labels are ready-made Russian texts, so both formats agree.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.bot import texts
from app.db.models import Client, Operation, User
from app.domain.currency import Currency
from app.domain.day_report import DayReport
from app.domain.entries import OperationType


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
