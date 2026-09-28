"""Reports (TZ 12.8, 13): data from the database, rendered to Excel or PDF."""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.domain.currency import Currency
from app.services.reports import data, excel, pdf
from app.services.reports.data import Period, ReportMeta


class ReportKind(StrEnum):
    # "Кто кому должен" (TZ 13.2) is a part of the summary since 28.09.2026.
    SUMMARY = "summary"
    RECORDS = "records"
    CASH = "cash"
    STATEMENT = "statement"


class ReportFormat(StrEnum):
    XLSX = "xlsx"
    PDF = "pdf"


PERIOD_KINDS = frozenset({ReportKind.RECORDS, ReportKind.CASH, ReportKind.STATEMENT})

_RENDERERS: dict[tuple[ReportKind, ReportFormat], Callable[[Any], bytes]] = {
    (ReportKind.SUMMARY, ReportFormat.XLSX): excel.summary_xlsx,
    (ReportKind.SUMMARY, ReportFormat.PDF): pdf.summary_pdf,
    (ReportKind.RECORDS, ReportFormat.XLSX): excel.records_xlsx,
    (ReportKind.RECORDS, ReportFormat.PDF): pdf.records_pdf,
    (ReportKind.CASH, ReportFormat.XLSX): excel.cash_xlsx,
    (ReportKind.CASH, ReportFormat.PDF): pdf.cash_pdf,
    (ReportKind.STATEMENT, ReportFormat.XLSX): excel.statement_xlsx,
    (ReportKind.STATEMENT, ReportFormat.PDF): pdf.statement_pdf,
}

_UNSAFE_IN_FILE_NAME = re.compile(r"[^\w().\-]+")


@dataclass(frozen=True)
class ReportFile:
    filename: str
    content: bytes


def _safe(text: str) -> str:
    """ "Иван (Ош)" -> "Иван_(Ош)"; no path separators or other odd characters."""
    return _UNSAFE_IN_FILE_NAME.sub("_", text).strip("_")[:60] or texts.REPORT_FILE_CLIENT_FALLBACK


def file_name(
    kind: ReportKind,
    fmt: ReportFormat,
    generated_at: datetime,
    period: Period | None = None,
    client_name: str | None = None,
) -> str:
    """ "Общая_сводка_2026-09-27.xlsx", "Выписка_Иван_2026-09-01_2026-09-30.pdf" (TZ 13)."""
    parts = [texts.REPORT_FILE_PREFIXES[kind]]
    if client_name is not None:
        parts.append(_safe(client_name))
    parts.append(period.file_part if period is not None else f"{generated_at:%Y-%m-%d}")
    return f"{'_'.join(parts)}.{fmt}"


async def build_report(
    session: AsyncSession,
    kind: ReportKind,
    fmt: ReportFormat,
    *,
    generated_by: str,
    generated_at: datetime,
    period: Period | None = None,
    client_id: int | None = None,
    rates: dict[Currency, Decimal] | None = None,
) -> ReportFile:
    meta = ReportMeta(
        title=texts.REPORT_TITLES[kind],
        generated_at=generated_at,
        generated_by=generated_by,
        period=period if kind in PERIOD_KINDS else None,
    )
    client_name = None
    report: Any
    match kind:
        case ReportKind.SUMMARY:
            report = await data.summary_data(session, meta, rates or {})
        case ReportKind.RECORDS:
            report = await data.records_data(session, meta, period or Period())
        case ReportKind.CASH:
            report = await data.cash_data(session, meta, period or Period())
        case ReportKind.STATEMENT:
            assert client_id is not None
            report = await data.statement_data(session, meta, period or Period(), client_id)
            client_name = report.client
    # openpyxl and reportlab are CPU-bound: keep the event loop free for other users.
    content = await asyncio.to_thread(_RENDERERS[(kind, fmt)], report)
    return ReportFile(
        file_name(kind, fmt, generated_at, meta.period, client_name),
        content,
    )
