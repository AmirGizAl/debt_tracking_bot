"""PDF reports: report dataclasses -> PDF bytes (TZ 8.4, 14). Pure functions, no database.

A4 (landscape for the journal, the cash movements and the day report with its records),
DejaVu Sans for Cyrillic, table headers repeated on every page, "Страница N из M" at the
bottom, grey text for cancelled records and cancellations.
"""

from collections.abc import Sequence
from decimal import Decimal
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.bot import texts
from app.domain.currency import HOME_CURRENCY
from app.domain.day_report import NameLine
from app.domain.money import format_amount, format_money, format_rate, format_signed
from app.services.reports.data import DayReportData, JournalRow, Money, ReportMeta

FONTS = Path(__file__).resolve().parents[2] / "assets" / "fonts"
FONT, FONT_BOLD = "DejaVuSans", "DejaVuSans-Bold"
MARGIN = 15 * mm
GREY_TEXT = colors.HexColor("#8C8C8C")
HEADER_BACKGROUND = colors.HexColor("#DDEBF7")


@cache
def _register_fonts() -> None:
    pdfmetrics.registerFont(TTFont(FONT, str(FONTS / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(
        FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD
    )


class _NumberedCanvas(Canvas):
    """Draws "Страница N из M": pages are kept until the total is known."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for page in self._pages:
            self.__dict__.update(page)
            self.setFont(FONT, 8)
            self.drawRightString(
                self._pagesize[0] - MARGIN, 8 * mm, texts.report_page(self._pageNumber, total)
            )
            super().showPage()
        super().save()


class _Styles:
    def __init__(self, size: float = 8.5) -> None:
        _register_fonts()  # Paragraphs resolve fonts as soon as they are created
        self.title = ParagraphStyle("title", fontName=FONT_BOLD, fontSize=14, leading=18)
        self.meta = ParagraphStyle("meta", fontName=FONT, fontSize=9, leading=12)
        # keepWithNext: a heading never stays alone at the bottom of a page.
        self.heading = ParagraphStyle(
            "heading",
            fontName=FONT_BOLD,
            fontSize=11,
            leading=14,
            spaceBefore=8,
            spaceAfter=4,
            keepWithNext=1,
        )
        self.text = ParagraphStyle("text", fontName=FONT, fontSize=9, leading=12)
        self.lead = ParagraphStyle("lead", parent=self.text, keepWithNext=1)
        self.subheading = ParagraphStyle(
            "subheading",
            fontName=FONT_BOLD,
            fontSize=9.5,
            leading=12,
            spaceBefore=4,
            spaceAfter=2,
            keepWithNext=1,
        )
        self.cell = ParagraphStyle("cell", fontName=FONT, fontSize=size, leading=size * 1.25)
        self.number = ParagraphStyle("number", parent=self.cell, alignment=TA_RIGHT)
        self.header = ParagraphStyle("header", parent=self.cell, fontName=FONT_BOLD)


def _paragraph(
    text: object,
    style: ParagraphStyle,
    *,
    bold: bool = False,
    grey: bool = False,
    color: str | None = None,
) -> Paragraph:
    content = escape("" if text is None else str(text))
    if bold:
        content = f"<b>{content}</b>"
    if grey:
        color = "#8C8C8C"
    if color is not None:
        content = f'<font color="{color}">{content}</font>'
    return Paragraph(content, style)


def _table(
    styles: _Styles,
    headers: Sequence[str],
    rows: Sequence[tuple[Sequence[object], bool]],
    widths: Sequence[float],
    numeric: set[int],
    bold_rows: set[int] | None = None,
    row_colors: dict[int, str] | None = None,
) -> Table:
    """Header repeated on every page; numbers aligned right; grey rows in grey text."""
    bold_rows = bold_rows or set()
    row_colors = row_colors or {}
    data = [[_paragraph(title, styles.header) for title in headers]]
    for index, (cells, grey) in enumerate(rows):
        data.append(
            [
                _paragraph(
                    cell,
                    styles.number if column in numeric else styles.cell,
                    bold=index in bold_rows,
                    grey=grey,
                    color=row_colors.get(index),
                )
                for column, cell in enumerate(cells)
            ]
        )
    table = Table(data, colWidths=[width * mm for width in widths], repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#A6A6A6")),
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BACKGROUND),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _header(styles: _Styles, meta: ReportMeta, extra: Sequence[str] = ()) -> list[Flowable]:
    lines = [_paragraph(meta.title, styles.title)]
    if meta.scope is not None:
        lines.append(_paragraph(meta.scope, styles.meta))
    lines.append(_paragraph(texts.report_generated_line(meta.generated_at), styles.meta))
    lines.append(_paragraph(texts.report_author_line(meta.generated_by), styles.meta))
    lines.extend(_paragraph(line, styles.meta) for line in extra)
    lines.append(Spacer(1, 4 * mm))
    return lines


def _build(story: list[Flowable], meta: ReportMeta, wide: bool = False) -> bytes:
    _register_fonts()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4) if wide else A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=meta.title,
        author=meta.generated_by,
    )
    document.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()


def _amount(value: Decimal | None) -> str:
    return "" if value is None else format_amount(value)


GREEN_TEXT, RED_TEXT = "#0A7D00", "#C00000"
# A4 landscape without the margins is 267 mm wide.
CURRENCY_WIDTHS = (34, 34, 34, 34, 34, 26, 40)
NAME_WIDTHS = (70, 40)
RESULT_WIDTHS = (80, 40)
JOURNAL_WIDTHS = (10, 10, 22, 23, 24, 22, 22, 24, 22, 22, 24, 18, 24)


def _money(value: Money | None) -> str:
    return "" if value is None else format_money(value.amount, value.currency)


def _names(styles: _Styles, lines: list[NameLine], total: Decimal) -> Flowable:
    if not lines:
        return _paragraph(texts.NOBODY_OWES, styles.text)
    rows = [([line.name, format_amount(line.amount)], False) for line in lines]
    rows.append(([texts.REPORT_TOTAL, format_amount(total)], False))
    return _table(styles, texts.NAME_COLUMNS, rows, NAME_WIDTHS, {1}, {len(rows) - 1})


def _report_blocks(styles: _Styles, data: DayReportData) -> list[Flowable]:
    """Blocks 1-4 of TZ 8.4."""
    report = data.report
    story: list[Flowable] = [_paragraph(texts.BLOCK_CURRENCIES, styles.heading)]
    rows = []
    for line in report.lines:
        home = line.currency == HOME_CURRENCY
        cells = [
            texts.KGS_OF_EXCHANGES if home else str(line.currency),
            texts.NO_DASH if line.cash is None else format_amount(line.cash),
            format_amount(line.owed_to_us),
            format_amount(line.we_owe),
            format_amount(line.position),
            "" if line.rate is None else format_rate(line.rate),
            format_amount(line.kgs),
        ]
        rows.append((cells, False))
    rows.append(
        (
            [texts.CURRENCIES_TOTAL, "", "", "", "", "", format_amount(report.currencies_total)],
            False,
        )
    )
    story.append(
        _table(
            styles, texts.CURRENCY_COLUMNS, rows, CURRENCY_WIDTHS, set(range(1, 7)), {len(rows) - 1}
        )
    )
    story.append(_paragraph(texts.BLOCK_CASH, styles.heading))
    story.append(_paragraph(format_money(report.cash_kgs, HOME_CURRENCY), styles.text))
    story.append(_paragraph(texts.BLOCK_LOANS, styles.heading))
    story.append(_paragraph(texts.owed_to_us_title(), styles.subheading))
    story.append(_names(styles, report.loans_owed_to_us, report.loans_owed_to_us_total))
    story.append(_paragraph(texts.we_owe_title(), styles.subheading))
    story.append(_names(styles, report.loans_we_owe, report.loans_we_owe_total))

    story.append(_paragraph(texts.BLOCK_RESULT, styles.heading))
    result = [
        ([texts.RESULT_TOTAL, format_amount(report.total)], False),
        ([texts.RESULT_BASELINE, format_amount(report.baseline_total)], False),
    ]
    result += [
        (
            [
                f"· {texts.baseline_line(line.currency, line.base, line.rate)}",
                format_amount(line.kgs),
            ],
            False,
        )
        for line in report.baseline
    ]
    surplus_index = len(result)
    result += [
        ([texts.RESULT_SURPLUS, format_signed(report.surplus)], False),
        ([texts.RESULT_CHANGE, format_signed(report.change)], False),
    ]
    color = GREEN_TEXT if report.surplus >= 0 else RED_TEXT
    table = _table(
        styles,
        texts.RESULT_COLUMNS,
        result,
        RESULT_WIDTHS,
        {1},
        {0, surplus_index},
        {surplus_index: color},
    )
    story.append(table)
    return story


def _exchange_blocks(styles: _Styles, data: DayReportData) -> list[Flowable]:
    """Block 5: for every currency, who owes us and whom we owe."""
    story: list[Flowable] = [_paragraph(texts.BLOCK_EXCHANGES, styles.heading)]
    if not data.report.exchanges:
        story.append(_paragraph(texts.NOBODY_OWES, styles.text))
    for item in data.report.exchanges:
        for title, lines in (
            (texts.owed_to_us_title(item.currency), item.owed_to_us),
            (texts.we_owe_title(item.currency), item.we_owe),
        ):
            if lines:
                total = sum((line.amount for line in lines), Decimal(0))
                story.append(_paragraph(title, styles.subheading))
                story.append(_names(styles, lines, total))
    return story


def journal_table(styles: _Styles, records: list[JournalRow]) -> Flowable:
    """The columns of TZ 14.3."""
    if not records:
        return _paragraph(texts.NO_RECORDS, styles.text)
    rows = [
        (
            [
                row.number,
                row.day,
                f"{row.time:%d.%m.%Y %H:%M}",
                row.type_label,
                row.client,
                _money(row.gives),
                _money(row.gets),
                row.rate,
                row.execution,
                _money(row.amount),
                row.note,
                row.author,
                row.status,
            ],
            row.grey,
        )
        for row in records
    ]
    return _table(styles, texts.JOURNAL_COLUMNS, rows, JOURNAL_WIDTHS, {0, 1, 5, 6, 9})


def day_report_pdf(data: DayReportData) -> bytes:
    """TZ 8.4: every block one after another; landscape, as the records are wide."""
    styles = _Styles()
    small = _Styles(size=7)
    story = _header(styles, data.meta)
    story += _report_blocks(styles, data)
    story += _exchange_blocks(styles, data)
    story.append(_paragraph(texts.BLOCK_RECORDS, styles.heading))
    story.append(journal_table(small, data.records))
    return _build(story, data.meta, wide=True)
