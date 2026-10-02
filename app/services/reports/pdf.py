"""PDF reports: report dataclasses -> PDF bytes (TZ 13). Pure functions, no database.

A4 (landscape for all records and cash movements), DejaVu Sans for Cyrillic, table headers
repeated on every page, "Страница N из M" at the bottom, grey text for cancelled records
and reversals.
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
from app.domain.money import format_amount
from app.services.reports.data import ReportMeta

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
    text: object, style: ParagraphStyle, *, bold: bool = False, grey: bool = False
) -> Paragraph:
    content = escape("" if text is None else str(text))
    if bold:
        content = f"<b>{content}</b>"
    if grey:
        content = f'<font color="#8C8C8C">{content}</font>'
    return Paragraph(content, style)


def _table(
    styles: _Styles,
    headers: Sequence[str],
    rows: Sequence[tuple[Sequence[object], bool]],
    widths: Sequence[float],
    numeric: set[int],
    bold_rows: set[int] | None = None,
) -> Table:
    """Header repeated on every page; numbers aligned right; grey rows in grey text."""
    bold_rows = bold_rows or set()
    data = [[_paragraph(title, styles.header) for title in headers]]
    for index, (cells, grey) in enumerate(rows):
        data.append(
            [
                _paragraph(
                    cell,
                    styles.number if column in numeric else styles.cell,
                    bold=index in bold_rows,
                    grey=grey,
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
