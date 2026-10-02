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
from app.services.reports.data import ReportMeta

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
