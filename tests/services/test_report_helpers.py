"""The shared Excel and PDF helpers kept from version 1 for the reports of version 2."""

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook

from app.services.reports import excel, pdf
from app.services.reports.data import ReportMeta

META = ReportMeta(
    title="Проверка",
    generated_at=datetime(2026, 10, 2, 14, 20, tzinfo=ZoneInfo("Europe/Moscow")),
    generated_by="Владелец",
    scope="День №1 · 02.10.2026",
)


def test_excel_table_has_frozen_header_filter_and_money_format() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    start = excel._meta(sheet, META)
    last = excel._table(
        sheet, start, ("Валюта", "Сумма"), [(["USD", Decimal("1000.50")], False)], money={2}
    )
    excel._fit_columns(sheet, start)

    reread = load_workbook(BytesIO(excel._save(workbook))).active
    assert reread is not None
    assert [reread.cell(row, 1).value for row in range(1, 5)] == [
        "Проверка",
        "День №1 · 02.10.2026",
        "Сформирован: 02.10.2026 14:20",
        "Сформировал: Владелец",
    ]
    assert reread.freeze_panes == f"A{start + 1}"
    assert reread.auto_filter.ref == f"A{start}:B{last}"
    assert reread.cell(last, 2).number_format == "#,##0.00"


def test_pdf_uses_dejavu_and_numbers_pages() -> None:
    styles = pdf._Styles()
    story = pdf._header(styles, META)
    story.append(
        pdf._table(styles, ("Валюта", "Сумма"), [(["USD", "1 000,50"], False)], [40, 40], {1})
    )

    content = pdf._build(story, META)

    assert content.startswith(b"%PDF")
    assert b"DejaVuSans" in content
