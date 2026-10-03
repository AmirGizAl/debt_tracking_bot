"""Reports (TZ 8.4, 14): data from the database, rendered to Excel or PDF."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Operation, User
from app.domain.currency import Currency
from app.services import days
from app.services.reports import excel, pdf
from app.services.reports.data import DayReportData, ReportFormat, ReportMeta, journal_rows

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
