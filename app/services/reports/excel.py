"""Excel reports: report dataclasses -> .xlsx bytes (TZ 13). Pure functions, no database.

Every table has a frozen header row and an autofilter; numbers are real numbers with the
"#,##0.00" format; cancelled records and reversals are filled grey.
"""

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.bot import texts
from app.services.reports.data import (
    CashReport,
    DebtSection,
    RecordsReport,
    ReportMeta,
    StatementReport,
    SummaryReport,
    balance_phrase,
)

MONEY_FORMAT = "#,##0.00"
DATE_FORMAT = "DD.MM.YYYY"
DATETIME_FORMAT = "DD.MM.YYYY HH:MM"
GREY_FILL = PatternFill("solid", fgColor="D9D9D9")
HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=14)
MIN_WIDTH, MAX_WIDTH = 8, 60

Row = tuple[Sequence[Any], bool]  # cell values and "grey"


def _save(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _excel_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)  # Excel has no time zones; values are local already
    if hasattr(value, "value") and isinstance(value.value, str):  # enums
        return value.value
    return value


def _meta(sheet: Worksheet, meta: ReportMeta, extra: Iterable[str] = ()) -> int:
    """Title, period, time, author (and extra lines); returns the first free row."""
    sheet.cell(1, 1, meta.title).font = TITLE
    lines = []
    if meta.period is not None:
        lines.append(texts.report_period_line(meta.period.label))
    lines.append(texts.report_generated_line(meta.generated_at))
    lines.append(texts.report_author_line(meta.generated_by))
    lines.extend(extra)
    for offset, line in enumerate(lines, start=2):
        sheet.cell(offset, 1, line)
    return len(lines) + 3  # one blank row after the header block


def _table(
    sheet: Worksheet,
    header_row: int,
    headers: Sequence[str],
    rows: Sequence[Row],
    money: Iterable[int] = (),
    dates: Iterable[int] = (),
    datetimes: Iterable[int] = (),
    bold_rows: Iterable[int] = (),
) -> int:
    """Write a table with a frozen, filterable header; returns the last written row."""
    money, dates, datetimes, bold_rows = set(money), set(dates), set(datetimes), set(bold_rows)
    for column, title in enumerate(headers, start=1):
        cell = sheet.cell(header_row, column, title)
        cell.font = BOLD
        cell.fill = HEADER_FILL
    row_number = header_row
    for index, (values, grey) in enumerate(rows):
        row_number += 1
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row_number, column, _excel_value(value))
            if column in money and isinstance(value, Decimal):
                cell.number_format = MONEY_FORMAT
            elif column in dates and isinstance(value, date):
                cell.number_format = DATE_FORMAT
            elif column in datetimes and isinstance(value, datetime):
                cell.number_format = DATETIME_FORMAT
            if grey:
                cell.fill = GREY_FILL
            if index in bold_rows:
                cell.font = BOLD
    sheet.freeze_panes = sheet.cell(header_row + 1, 1)
    last_column = get_column_letter(len(headers))
    sheet.auto_filter.ref = f"A{header_row}:{last_column}{max(row_number, header_row)}"
    return row_number


def _fit_columns(sheet: Worksheet, from_row: int) -> None:
    """Column widths by content, ignoring the title block above the tables."""
    widths: dict[int, int] = {}
    for row in sheet.iter_rows(min_row=from_row):
        for cell in row:
            if cell.value is None:
                continue
            value = cell.value
            if isinstance(value, Decimal | int | float):
                text = f"{value:,.2f}"
            elif isinstance(value, datetime):
                text = "00.00.0000 00:00"
            elif isinstance(value, date):
                text = "00.00.0000"
            else:
                text = str(value)
            longest = max(len(line) for line in text.splitlines()) if text else 0
            widths[cell.column] = max(widths.get(cell.column, 0), longest)
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = min(
            max(width + 2, MIN_WIDTH), MAX_WIDTH
        )


def _labelled_value(sheet: Worksheet, row: int, label: str, *cells: tuple[int, Any]) -> None:
    sheet.cell(row, 1, label).font = BOLD
    for column, value in cells:
        cell = sheet.cell(row, column, _excel_value(value))
        cell.font = BOLD
        if isinstance(value, Decimal):
            cell.number_format = MONEY_FORMAT


# --- reports -----------------------------------------------------------------------------------


def summary_xlsx(report: SummaryReport) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = texts.SUMMARY_SHEET_BY_CURRENCY
    start = _meta(sheet, report.meta)
    sheet.cell(start, 1, texts.SUMMARY_TITLE_BY_CURRENCY).font = BOLD
    rows: list[Row] = [
        ([row.currency, row.cash, row.owed_to_you, row.you_owe, row.difference], False)
        for row in report.rows
    ]
    _table(
        sheet,
        start + 1,
        texts.SUMMARY_COLUMNS,
        rows,
        money={2, 3, 4, 5},
    )
    _fit_columns(sheet, start + 1)

    sheet = workbook.create_sheet(texts.SUMMARY_SHEET_IN_KGS)
    start = _meta(sheet, report.meta)
    sheet.cell(start, 1, texts.SUMMARY_TITLE_IN_KGS).font = BOLD
    rows = [([row.currency, row.cash, row.rate, row.kgs], False) for row in report.kgs_rows]
    last = _table(
        sheet,
        start + 1,
        texts.SUMMARY_KGS_COLUMNS,
        rows,
        money={2, 4},
    )
    _labelled_value(sheet, last + 1, texts.REPORT_TOTAL, (4, report.kgs_total))
    _fit_columns(sheet, start + 1)

    # "Кто кому должен" (TZ 13.2): a sheet per direction, currencies one after another.
    _debts_sheet(workbook, report.meta, texts.REPORT_OWED_TO_YOU, report.owed_to_you)
    _debts_sheet(workbook, report.meta, texts.REPORT_YOU_OWE, report.you_owe)
    return _save(workbook)


def _debts_sheet(
    workbook: Workbook, meta: ReportMeta, title: str, sections: list[DebtSection]
) -> None:
    sheet = workbook.create_sheet(title)
    start = _meta(sheet, meta, [title])
    rows: list[Row] = []
    bold_rows: list[int] = []
    for section in sections:
        rows.extend(([section.currency, line.client, line.amount], False) for line in section.lines)
        bold_rows.append(len(rows))
        rows.append(([section.currency, texts.REPORT_TOTAL_BY_CURRENCY, section.total], False))
    if not rows:
        rows.append((["", texts.REPORT_NO_DEBTS, None], False))
    _table(sheet, start, texts.DEBTS_COLUMNS, rows, money={3}, bold_rows=bold_rows)
    _fit_columns(sheet, start)


def records_xlsx(report: RecordsReport) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = texts.RECORDS_SHEET
    start = _meta(sheet, report.meta)
    rows: list[Row] = [
        (
            [
                row.number,
                row.op_date,
                row.operation,
                row.client,
                row.debt_amount,
                row.debt_currency,
                row.pay_amount,
                row.pay_currency,
                row.rate,
                row.comment,
                row.author,
                row.created_at,
                row.status,
            ],
            row.grey,
        )
        for row in report.rows
    ]
    _table(
        sheet,
        start,
        texts.RECORDS_XLSX_COLUMNS,
        rows,
        money={5, 7},
        dates={2},
        datetimes={12},
    )
    _fit_columns(sheet, start)
    return _save(workbook)


def cash_xlsx(report: CashReport) -> bytes:
    workbook = Workbook()
    first = workbook.active
    assert first is not None
    if not report.sections:
        first.title = texts.CASH_REPORT_SHEET
        start = _meta(first, report.meta)
        first.cell(start, 1, texts.REPORT_NO_MOVEMENTS)
        return _save(workbook)
    for index, section in enumerate(report.sections):
        sheet = first if index == 0 else workbook.create_sheet()
        sheet.title = section.currency
        start = _meta(sheet, report.meta, [texts.report_currency_line(section.currency)])
        _labelled_value(sheet, start, texts.REPORT_OPENING, (6, section.opening))
        rows: list[Row] = [
            ([row.day, row.number, row.description, row.income, row.expense, row.balance], row.grey)
            for row in section.rows
        ]
        last = _table(
            sheet,
            start + 2,
            texts.CASH_REPORT_COLUMNS,
            rows,
            money={4, 5, 6},
            dates={1},
        )
        _labelled_value(sheet, last + 1, texts.REPORT_CLOSING, (6, section.closing))
        _fit_columns(sheet, start)
    return _save(workbook)


def statement_xlsx(report: StatementReport) -> bytes:
    workbook = Workbook()
    first = workbook.active
    assert first is not None
    extra = [texts.report_client_line(report.client)]
    if not report.sections:
        first.title = texts.STATEMENT_SHEET
        start = _meta(first, report.meta, extra)
        first.cell(start, 1, texts.REPORT_NO_RECORDS)
        return _save(workbook)
    for index, section in enumerate(report.sections):
        sheet = first if index == 0 else workbook.create_sheet()
        sheet.title = section.currency
        start = _meta(sheet, report.meta, [*extra, texts.report_currency_line(section.currency)])
        _labelled_value(
            sheet,
            start,
            texts.REPORT_OPENING,
            (3, balance_phrase(section.opening, section.currency)),
            (6, section.opening),
        )
        rows: list[Row] = [
            (
                [row.op_date, row.number, row.operation, row.change, row.payment, row.balance],
                row.grey,
            )
            for row in section.rows
        ]
        last = _table(
            sheet,
            start + 2,
            texts.STATEMENT_COLUMNS,
            rows,
            money={4, 6},
            dates={1},
        )
        _labelled_value(
            sheet,
            last + 1,
            texts.REPORT_CLOSING,
            (3, balance_phrase(section.closing, section.currency)),
            (6, section.closing),
        )
        _fit_columns(sheet, start)
    return _save(workbook)
