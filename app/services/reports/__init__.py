"""Reports (TZ 8.4, 14): data from the database, rendered to Excel or PDF."""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import BusinessDay, Operation, User
from app.domain.currency import Currency
from app.domain.errors import DayNotFound
from app.services import clients, days
from app.services.reports import excel, pdf
from app.services.reports.data import (
    DayReportData,
    JournalData,
    MovementData,
    Period,
    ReportFormat,
    ReportMeta,
    StatementData,
    WhoOwesData,
    journal_data,
    journal_rows,
    movement_data,
    statement_data,
    who_owes_data,
)

_DAY_RENDERERS: dict[ReportFormat, Callable[[DayReportData], bytes]] = {
    ReportFormat.XLSX: excel.day_report_xlsx,
    ReportFormat.PDF: pdf.day_report_pdf,
}


@dataclass(frozen=True)
class ReportFile:
    filename: str
    content: bytes


async def _render_day(data: DayReportData, fmt: ReportFormat) -> bytes:
    # openpyxl and reportlab are CPU-bound: keep the event loop free for other users.
    return await asyncio.to_thread(_DAY_RENDERERS[fmt], data)


async def preliminary_file(
    session: AsyncSession,
    rates: dict[Currency, Decimal],
    fmt: ReportFormat,
    *,
    generated_by: str,
    generated_at: datetime,
    zone: ZoneInfo,
) -> ReportFile:
    """TZ 8.3: the open day right now with the given rates; nothing is saved.

    Raises MissingRate if a currency without a rate has a position by now.
    """
    day, report = await days.preliminary_report(session, rates)
    meta = ReportMeta(
        title=texts.preliminary_title(day.id, generated_at),
        generated_at=generated_at,
        generated_by=generated_by,
    )
    records = await journal_rows(session, zone, Operation.day_id == day.id)
    content = await _render_day(DayReportData(meta, report, records), fmt)
    return ReportFile(texts.preliminary_file_name(day.id, generated_at, fmt), content)


async def closed_day_file(
    session: AsyncSession,
    day_id: int,
    fmt: ReportFormat,
    *,
    generated_by: str,
    generated_at: datetime,
    zone: ZoneInfo,
) -> ReportFile:
    """TZ 8.5: from the snapshot of the day, never recalculated; its records by `day_id`."""
    day, report = await days.archived_report(session, day_id)
    assert day.closed_at is not None and day.closed_by_id is not None
    closed_at = day.closed_at.astimezone(zone)
    closer = await session.get(User, day.closed_by_id)
    assert closer is not None
    meta = ReportMeta(
        title=texts.day_report_title(day.id, closed_at.date()),
        generated_at=generated_at,
        generated_by=generated_by,
        scope=texts.closed_by_line(texts.user_name(closer), closed_at),
    )
    records = await journal_rows(session, zone, Operation.day_id == day.id)
    content = await _render_day(DayReportData(meta, report, records), fmt)
    return ReportFile(texts.day_report_file_name(day.id, closed_at.date(), fmt), content)


_RENDERERS: dict[type, dict[ReportFormat, Callable[..., bytes]]] = {
    WhoOwesData: {ReportFormat.XLSX: excel.who_owes_xlsx, ReportFormat.PDF: pdf.who_owes_pdf},
    JournalData: {ReportFormat.XLSX: excel.journal_xlsx, ReportFormat.PDF: pdf.journal_pdf},
    MovementData: {ReportFormat.XLSX: excel.movement_xlsx, ReportFormat.PDF: pdf.movement_pdf},
    StatementData: {
        ReportFormat.XLSX: excel.statement_xlsx,
        ReportFormat.PDF: pdf.statement_pdf,
    },
}
_UNSAFE_IN_FILE_NAME = re.compile(r"[^\w().\-]+")


async def _render(
    data: WhoOwesData | JournalData | MovementData | StatementData, fmt: ReportFormat
) -> bytes:
    return await asyncio.to_thread(_RENDERERS[type(data)][fmt], data)


def _safe(text: str) -> str:
    """ "Иван (Ош)" -> "Иван_(Ош)": no path separators or other odd characters."""
    return _UNSAFE_IN_FILE_NAME.sub("_", text).strip("_")[:60] or texts.FILE_CLIENT_FALLBACK


async def _period_texts(
    session: AsyncSession, period: Period, generated_at: datetime, zone: ZoneInfo
) -> tuple[str, str]:
    """The line of the period in the header and its part of the file name."""
    if period.day_id is not None:
        day = await session.get(BusinessDay, period.day_id, populate_existing=True)
        if day is None:
            raise DayNotFound(period.day_id)
        closed_on = day.closed_at.astimezone(zone).date() if day.closed_at else None
        return texts.day_scope(day.id, closed_on), texts.file_part_day(day.id, generated_at)
    if period.start is not None and period.end is not None:
        return (
            texts.dates_scope(period.start, period.end),
            texts.file_part_dates(period.start, period.end),
        )
    return texts.PERIOD_ALL_TIME, texts.file_part_all_time(generated_at)


async def who_owes_file(
    session: AsyncSession,
    fmt: ReportFormat,
    *,
    generated_by: str,
    generated_at: datetime,
    zone: ZoneInfo,
) -> ReportFile:
    """TZ 14.2: obligations right now."""
    meta = ReportMeta(
        texts.WHO_OWES_TITLE, generated_at, generated_by, texts.who_owes_scope(generated_at)
    )
    content = await _render(await who_owes_data(session, meta), fmt)
    name = texts.report_file_name(texts.FILE_WHO_OWES, texts.file_part_moment(generated_at), fmt)
    return ReportFile(name, content)


async def journal_file(
    session: AsyncSession,
    period: Period,
    fmt: ReportFormat,
    *,
    generated_by: str,
    generated_at: datetime,
    zone: ZoneInfo,
) -> ReportFile:
    """TZ 14.3."""
    scope, part = await _period_texts(session, period, generated_at, zone)
    meta = ReportMeta(texts.JOURNAL_TITLE, generated_at, generated_by, scope)
    content = await _render(await journal_data(session, meta, period, zone), fmt)
    return ReportFile(texts.report_file_name(texts.FILE_JOURNAL, part, fmt), content)


async def movement_file(
    session: AsyncSession,
    period: Period,
    fmt: ReportFormat,
    *,
    generated_by: str,
    generated_at: datetime,
    zone: ZoneInfo,
) -> ReportFile:
    """TZ 14.4."""
    scope, part = await _period_texts(session, period, generated_at, zone)
    meta = ReportMeta(texts.MOVEMENT_TITLE, generated_at, generated_by, scope)
    content = await _render(await movement_data(session, meta, period, zone), fmt)
    return ReportFile(texts.report_file_name(texts.FILE_MOVEMENT, part, fmt), content)


async def statement_file(
    session: AsyncSession,
    client_id: int,
    period: Period,
    fmt: ReportFormat,
    *,
    generated_by: str,
    generated_at: datetime,
    zone: ZoneInfo,
) -> ReportFile:
    """TZ 14.5; raises ClientNotFound."""
    client = await clients.get_client(session, client_id)
    scope, part = await _period_texts(session, period, generated_at, zone)
    meta = ReportMeta(texts.statement_title(client.name), generated_at, generated_by, scope)
    content = await _render(await statement_data(session, meta, period, zone, client), fmt)
    prefix = f"{texts.FILE_STATEMENT}_{_safe(client.name)}"
    return ReportFile(texts.report_file_name(prefix, part, fmt), content)
