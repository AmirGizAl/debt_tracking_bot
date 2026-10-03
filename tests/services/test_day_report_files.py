"""The files of the day report (TZ 8.4, 8.5; 18: «Отчёты»)."""

from datetime import datetime
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, User
from app.domain.errors import MissingRate
from app.services import days, reports
from app.services.reports.data import ReportFormat, journal_rows
from tests.services.accounting import (
    DAY_1_RATES,
    DAY_2_RATES,
    KGS,
    USD,
    D,
    acceptance_day_1,
    acceptance_day_2,
    cancel,
    swap,
)

MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 2, 18, 5, tzinfo=MOSCOW)
XLSX, PDF = ReportFormat.XLSX, ReportFormat.PDF


async def close_day_1(session: AsyncSession, owner: User) -> dict[str, Client]:
    """Scenarios 1-8 of TZ 17.1: day №1 closed with the rates of the control example."""
    await days.ensure_open_day(session)
    people = await acceptance_day_1(session, owner)
    await days.close_day(session, owner, 1, DAY_1_RATES)
    return people


async def day_file(session: AsyncSession, day_id: int, fmt: ReportFormat) -> reports.ReportFile:
    return await reports.closed_day_file(
        session, day_id, fmt, generated_by="Владелец", generated_at=NOW, zone=MOSCOW
    )


async def day_workbook(session: AsyncSession, day_id: int) -> Any:
    return load_workbook(BytesIO((await day_file(session, day_id, XLSX)).content))


def row_of(sheet: Worksheet, label: str) -> list[Any]:
    """The values of the first row whose first cell is `label`."""
    for row in sheet.iter_rows(values_only=True):
        if row[0] == label:
            return list(row)
    raise AssertionError(f"no row {label!r}")


def record_numbers(sheet: Worksheet) -> list[int]:
    return [row[0] for row in sheet.iter_rows(values_only=True) if isinstance(row[0], int)]


async def test_excel_of_the_control_example(session: AsyncSession, owner: User) -> None:
    await close_day_1(session, owner)
    day, _ = await days.archived_report(session, 1)
    assert day.closed_at is not None
    closed_on = day.closed_at.astimezone(MOSCOW)

    report = await day_file(session, 1, XLSX)

    assert report.filename == f"Отчёт_дня_1_{closed_on:%Y-%m-%d}.xlsx"
    book = load_workbook(BytesIO(report.content))
    assert book.sheetnames == ["Отчёт", "Обмены", "Записи дня"]
    sheet = book["Отчёт"]
    assert sheet["A1"].value == f"Отчёт дня №1 · {closed_on:%d.%m.%Y}"
    assert sheet["A2"].value == f"Закрыл: Владелец · {closed_on:%d.%m.%Y %H:%M}"
    # TZ 8.6.
    assert row_of(sheet, "USD")[:7] == ["USD", 10000, 0, 1000, 9000, 87.65, 788850]
    assert row_of(sheet, "RUB")[4:7] == [88500, 0.991, 87703.5]
    assert row_of(sheet, "KGS (обмены)")[:7] == ["KGS (обмены)", "—", 0, 0, 0, 1, 0]
    assert row_of(sheet, "Итого по валютам")[6] == 876553.5
    assert row_of(sheet, "Наличка")[1] == 951000
    assert row_of(sheet, "Бекзат")[:2] == ["Бекзат", 50000]
    assert row_of(sheet, "Итог")[1] == 1877553.5
    assert row_of(sheet, "Начальная точка")[1] == 1876500
    # Amounts in texts keep their non-breaking spaces (TZ 4.4).
    assert row_of(sheet, "· USD: 10\u00a0000 × 87,65")[1] == 876500
    assert row_of(sheet, "· KGS: 1\u00a0000\u00a0000")[1] == 1000000
    assert row_of(sheet, "Излишки")[1] == 1053.5
    assert row_of(sheet, "Изменение за день")[1] == 1053.5
    surplus = next(row for row in sheet.iter_rows() if row[0].value == "Излишки")[1]
    assert surplus.font.color.rgb.endswith("0A7D00")  # green: not below zero

    exchanges = book["Обмены"]
    azamat = next(row for row in exchanges.iter_rows() if row[2].value == "Азамат")
    assert [cell.value for cell in azamat] == ["USD", "Мы должны", "Азамат", 1000]
    assert azamat[3].number_format.endswith('"USD"')

    records = book["Записи дня"]
    assert record_numbers(records) == [1, 2, 3, 4, 5, 6]
    deal = next(row for row in records.iter_rows() if row[0].value == 5)
    assert [cell.value for cell in deal][3:9] == [
        "Обмен",
        "Азамат",
        88500,
        1000,
        "1 USD = 88,5 RUB",
        "получено, выдача позже",
    ]
    assert deal[5].number_format.endswith('"RUB"')
    assert deal[6].number_format.endswith('"USD"')


async def test_pdf_is_a_pdf_with_a_cyrillic_font(session: AsyncSession, owner: User) -> None:
    await close_day_1(session, owner)

    report = await day_file(session, 1, PDF)

    assert report.filename.endswith(".pdf")
    assert report.content.startswith(b"%PDF")
    assert b"DejaVuSans" in report.content
    assert len(report.content) > 5000


async def test_archive_of_day_1_does_not_change_on_day_2(
    session: AsyncSession, owner: User
) -> None:
    people = await close_day_1(session, owner)
    before = await day_workbook(session, 1)

    # TZ 17.1, scenarios 9-11.
    await acceptance_day_2(session, owner, people["Азамат"])
    await days.close_day(session, owner, 2, DAY_2_RATES)

    after = await day_workbook(session, 1)
    assert row_of(after["Отчёт"], "Излишки") == row_of(before["Отчёт"], "Излишки")
    assert row_of(after["Отчёт"], "Итог")[1] == 1877553.5
    assert record_numbers(after["Записи дня"]) == record_numbers(before["Записи дня"])
    day_2 = await day_workbook(session, 2)
    assert row_of(day_2["Отчёт"], "Итог")[1] == 1878315
    assert row_of(day_2["Отчёт"], "Начальная точка")[1] == 1877000
    assert row_of(day_2["Отчёт"], "Излишки")[1] == 1315
    assert row_of(day_2["Отчёт"], "Изменение за день")[1] == 261.5
    assert record_numbers(day_2["Записи дня"]) == [7, 8]


async def test_preliminary_file(session: AsyncSession, owner: User) -> None:
    await days.ensure_open_day(session)
    await acceptance_day_1(session, owner)

    report = await reports.preliminary_file(
        session, DAY_1_RATES, XLSX, generated_by="Айгуль", generated_at=NOW, zone=MOSCOW
    )

    assert report.filename == "Предварительный_отчёт_день_1_2026-10-02_1805.xlsx"
    sheet = load_workbook(BytesIO(report.content))["Отчёт"]
    assert sheet["A1"].value == "Предварительный отчёт · день №1 · 02.10.2026 18:05"
    assert sheet["A3"].value == "Сформировал: Айгуль"
    assert row_of(sheet, "Излишки")[1] == 1053.5
    assert (await days.ensure_open_day(session)).id == 1  # nothing is closed
    with pytest.raises(MissingRate):  # RUB has a position, its rate is missing
        await reports.preliminary_file(
            session, {USD: D("87.65")}, PDF, generated_by="Айгуль", generated_at=NOW, zone=MOSCOW
        )


async def test_journal_rows_show_cancellations_in_grey(session: AsyncSession, owner: User) -> None:
    await days.ensure_open_day(session)
    await acceptance_day_1(session, owner)
    sale = await swap(session, owner, "100", USD, "8700", KGS, rate="87")
    cancellation = await cancel(session, owner, sale, "дубль")

    rows = {row.number: row for row in await journal_rows(session, MOSCOW)}

    assert (rows[3].client, rows[3].execution, rows[3].grey) == ("без имени", "сразу", False)
    loan = rows[6]
    assert (loan.type_label, loan.client, loan.gives) == ("Выдал в долг", "Бекзат", None)
    assert loan.amount is not None
    assert (loan.amount.amount, loan.amount.currency) == (D("50000"), KGS)
    assert (rows[sale.id].status, rows[sale.id].grey) == (
        f"отменена записью №{cancellation.id}",
        True,
    )
    assert (rows[cancellation.id].status, rows[cancellation.id].grey) == (
        f"отмена записи №{sale.id} (дубль)",
        True,
    )
