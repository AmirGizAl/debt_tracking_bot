"""Excel reports: report dataclasses -> .xlsx bytes (TZ 8.4, 14). Pure functions, no database.

The main table of every sheet has a frozen header row and an autofilter; numbers are real
numbers with the "#,##0.00" format (money of different currencies shows its code); cancelled
records and cancellations are filled grey.
"""

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import Cell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.bot import texts
from app.domain.currency import HOME_CURRENCY, Currency
from app.domain.day_report import NameLine
from app.services.reports.data import DayReportData, JournalRow, ReportMeta

MONEY_FORMAT = "#,##0.00"
DATE_FORMAT = "DD.MM.YYYY"
DATETIME_FORMAT = "DD.MM.YYYY HH:MM"
GREY_FILL = PatternFill("solid", fgColor="D9D9D9")
HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=14)
MIN_WIDTH, MAX_WIDTH = 8, 60
PLAIN_WIDTH, BOLD_WIDTH = 1.1, 1.4  # units of column width per character (Calibri 11)

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
    if meta.scope is not None:
        lines.append(meta.scope)
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
    filtered: bool = True,
) -> int:
    """Write a table; returns the last written row.

    The first table of a sheet gets the frozen, filterable header (`filtered`): Excel allows one
    filter per sheet, so the smaller tables below it are plain.
    """
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
    if filtered:
        sheet.freeze_panes = sheet.cell(header_row + 1, 1)
        last_column = get_column_letter(len(headers))
        sheet.auto_filter.ref = f"A{header_row}:{last_column}{max(row_number, header_row)}"
    return row_number


def _shown_width(cell: Cell) -> float:
    """About how many characters the cell shows: numbers with their format, bold is wider."""
    value = cell.value
    if isinstance(value, Decimal | int | float):
        text = f"{value:,.2f}"
        suffix = re.search(r'"([^"]*)"', str(cell.number_format))  # e.g. ' "USD"'
        if suffix:
            text += f" {suffix.group(1)}"
    elif isinstance(value, datetime):
        text = "00.00.0000 00:00"
    elif isinstance(value, date):
        text = "00.00.0000"
    else:
        text = str(value)
    longest = max(len(line) for line in text.splitlines()) if text else 0
    return longest * (BOLD_WIDTH if cell.font is not None and cell.font.bold else PLAIN_WIDTH)


def _fit_columns(sheet: Worksheet, from_row: int) -> None:
    """Column widths by content, ignoring the title block above the tables; printed on A4
    landscape, every column on the width of one page."""
    widths: dict[int, float] = {}
    for row in sheet.iter_rows(min_row=from_row):
        for cell in row:
            if cell.value is not None:
                widths[cell.column] = max(widths.get(cell.column, 0), _shown_width(cell))
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = min(
            max(width + 2, MIN_WIDTH), MAX_WIDTH
        )
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True


def _labelled_value(sheet: Worksheet, row: int, label: str, *cells: tuple[int, Any]) -> None:
    sheet.cell(row, 1, label).font = BOLD
    for column, value in cells:
        cell = sheet.cell(row, column, _excel_value(value))
        cell.font = BOLD
        if isinstance(value, Decimal):
            cell.number_format = MONEY_FORMAT


SIGNED_FORMAT = "+#,##0.00;-#,##0.00;0.00"
GREEN = Font(bold=True, color="0A7D00")
RED = Font(bold=True, color="C00000")


def _money_format(currency: Currency) -> str:
    """ "1 000,00 USD" while the cell stays a number."""
    return f'{MONEY_FORMAT} "{currency}"'


def _heading(sheet: Worksheet, row: int, text: str) -> int:
    sheet.cell(row, 1, text).font = BOLD
    return row + 1


def _names_rows(lines: list[NameLine], total: Decimal) -> tuple[list[Row], set[int]]:
    """ "Имя | Сумма" from the largest, then «Итого» (bold); «Нет» for an empty list."""
    if not lines:
        return [([texts.NOBODY_OWES, None], False)], set()
    rows: list[Row] = [([line.name, line.amount], False) for line in lines]
    rows.append(([texts.REPORT_TOTAL, total], False))
    return rows, {len(rows) - 1}


def _report_sheet(sheet: Worksheet, data: DayReportData) -> None:
    """Blocks 1-4 of TZ 8.4: currencies, cash, som loans, the result."""
    report = data.report
    row = _heading(sheet, _meta(sheet, data.meta), texts.BLOCK_CURRENCIES)
    first = row
    rows: list[Row] = []
    for line in report.lines:
        home = line.currency == HOME_CURRENCY
        name = texts.KGS_OF_EXCHANGES if home else str(line.currency)
        cash = texts.NO_DASH if line.cash is None else line.cash
        values = [name, cash, line.owed_to_us, line.we_owe, line.position, line.rate, line.kgs]
        rows.append((values, False))
    rows.append(
        ([texts.CURRENCIES_TOTAL, None, None, None, None, None, report.currencies_total], False)
    )
    row = _table(
        sheet, row, texts.CURRENCY_COLUMNS, rows, money={2, 3, 4, 5, 7}, bold_rows={len(rows) - 1}
    )

    row += 2
    _labelled_value(sheet, row, texts.BLOCK_CASH, (2, report.cash_kgs))

    row = _heading(sheet, row + 2, texts.BLOCK_LOANS)
    for title, lines, total in (
        (texts.owed_to_us_title(), report.loans_owed_to_us, report.loans_owed_to_us_total),
        (texts.we_owe_title(), report.loans_we_owe, report.loans_we_owe_total),
    ):
        sheet.cell(row, 1, title).font = BOLD
        name_rows, bold = _names_rows(lines, total)
        row = _table(
            sheet, row + 1, texts.NAME_COLUMNS, name_rows, money={2}, bold_rows=bold, filtered=False
        )
        row += 2

    row = _heading(sheet, row, texts.BLOCK_RESULT)
    result: list[Row] = [
        ([texts.RESULT_TOTAL, report.total], False),
        ([texts.RESULT_BASELINE, report.baseline_total], False),
    ]
    result += [
        ([f"· {texts.baseline_line(line.currency, line.base, line.rate)}", line.kgs], False)
        for line in report.baseline
    ]
    result += [
        ([texts.RESULT_SURPLUS, report.surplus], False),
        ([texts.RESULT_CHANGE, report.change], False),
    ]
    last = _table(
        sheet,
        row,
        texts.RESULT_COLUMNS,
        result,
        money={2},
        bold_rows={0, len(result) - 2},
        filtered=False,
    )
    surplus, change = sheet.cell(last - 1, 2), sheet.cell(last, 2)
    surplus.font = GREEN if report.surplus >= 0 else RED
    surplus.number_format = change.number_format = SIGNED_FORMAT
    _fit_columns(sheet, first)


def _exchanges_sheet(sheet: Worksheet, data: DayReportData) -> None:
    """Block 5: obligations of the exchanges by name, every currency in both directions."""
    start = _meta(sheet, data.meta, [texts.BLOCK_EXCHANGES])
    rows: list[Row] = []
    bold: set[int] = set()
    formats: dict[int, Currency] = {}
    for item in data.report.exchanges:
        for direction, lines in (
            (texts.owed_to_us_title(), item.owed_to_us),
            (texts.we_owe_title(), item.we_owe),
        ):
            for line in lines:
                formats[len(rows)] = item.currency
                rows.append(([str(item.currency), direction, line.name, line.amount], False))
            if lines:
                formats[len(rows)] = item.currency
                bold.add(len(rows))
                total = sum((line.amount for line in lines), Decimal(0))
                rows.append(([str(item.currency), direction, texts.REPORT_TOTAL, total], False))
    if not rows:
        rows.append((["", "", texts.NOBODY_OWES, None], False))
    _table(sheet, start, texts.EXCHANGE_COLUMNS, rows, money={4}, bold_rows=bold)
    for index, currency in formats.items():
        sheet.cell(start + 1 + index, 4).number_format = _money_format(currency)
    _fit_columns(sheet, start)


def _journal_values(row: JournalRow) -> list[Any]:
    return [
        row.number,
        row.day,
        row.time,
        row.type_label,
        row.client,
        row.gives.amount if row.gives else None,
        row.gets.amount if row.gets else None,
        row.rate,
        row.execution,
        row.amount.amount if row.amount else None,
        row.note,
        row.author,
        row.status,
    ]


def journal_sheet(sheet: Worksheet, meta: ReportMeta, records: list[JournalRow]) -> None:
    """The columns of TZ 14.3; money keeps its currency in the number format."""
    start = _meta(sheet, meta)
    rows: list[Row] = [(_journal_values(row), row.grey) for row in records]
    if not rows:
        rows.append(([None, None, None, texts.NO_RECORDS], False))
    _table(sheet, start, texts.JOURNAL_COLUMNS, rows, money={6, 7, 10}, datetimes={3})
    for index, row in enumerate(records, start=start + 1):
        for column, money in ((6, row.gives), (7, row.gets), (10, row.amount)):
            if money is not None:
                sheet.cell(index, column).number_format = _money_format(money.currency)
    _fit_columns(sheet, start)


def day_report_xlsx(data: DayReportData) -> bytes:
    """TZ 8.4: blocks 1-4 on «Отчёт», block 5 on «Обмены», block 6 on «Записи дня»."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = texts.DAY_REPORT_SHEET
    _report_sheet(sheet, data)
    _exchanges_sheet(workbook.create_sheet(texts.EXCHANGES_SHEET), data)
    journal_sheet(workbook.create_sheet(texts.DAY_RECORDS_SHEET), data.meta, data.records)
    return _save(workbook)
