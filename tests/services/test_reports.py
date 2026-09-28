"""Reports: data (TZ 13) and files (TZ 16: xlsx opens in openpyxl, PDF starts with %PDF)."""

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.domain.currency import Currency
from app.domain.operations import OperationType
from app.services import reports
from app.services.reports import ReportFormat, ReportKind, data, excel, pdf
from app.services.reports.data import Period, ReportMeta
from tests.bot.harness import readable
from tests.factories import make_client
from tests.services.accounting import adjust, record, reverse, scenarios_1_to_8

KGS, USD, EUR, RUB, KZT = Currency.KGS, Currency.USD, Currency.EUR, Currency.RUB, Currency.KZT
D = Decimal
ZONE = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 9, 27, 18, 30, tzinfo=ZONE)
SEPTEMBER = Period(date(2026, 9, 1), date(2026, 9, 30))
SCENARIO_9_RATES = {USD: D("87.5"), EUR: D("100"), RUB: D("1.1"), KZT: D("0.17")}


def meta(title: str = "Отчёт", period: Period | None = None) -> ReportMeta:
    return ReportMeta(title=title, generated_at=NOW, generated_by="Владелец", period=period)


# --- 13.1 summary (TZ 15.1 scenario 9) ---------------------------------------------------------


async def test_summary_after_scenarios_1_to_8(session: AsyncSession, owner: User) -> None:
    await scenarios_1_to_8(session, owner)

    report = await data.summary_data(session, meta(), SCENARIO_9_RATES)

    assert [(r.currency, r.cash, r.owed_to_you, r.you_owe, r.difference) for r in report.rows] == [
        (KGS, D("352500"), 0, 0, 0),
        (USD, D("9100"), 0, 0, 0),
        (EUR, D("2000"), 0, 0, 0),
        (RUB, D("530000"), 0, D("3000"), D("-3000")),
        (KZT, D("1000000"), 0, 0, 0),
    ]
    assert [(r.currency, r.rate, r.kgs) for r in report.kgs_rows] == [
        (KGS, D("1"), D("352500")),
        (USD, D("87.5"), D("796250")),
        (EUR, D("100"), D("200000")),
        (RUB, D("1.1"), D("583000")),
        (KZT, D("0.17"), D("170000")),
    ]
    assert report.kgs_total == D("2101750")


def test_rates_are_asked_only_for_nonzero_foreign_cash() -> None:
    balances = {KGS: D("5"), USD: D("0"), EUR: D("1"), RUB: D("0"), KZT: D("-1")}
    assert data.currencies_needing_rates(balances) == [EUR, KZT]


async def test_summary_rounds_each_line_before_adding(session: AsyncSession, owner: User) -> None:
    await adjust(session, owner, "0.01", USD)
    await adjust(session, owner, "0.01", EUR)

    report = await data.summary_data(session, meta(), {USD: D("0.5"), EUR: D("0.5")})

    # 0.005 + 0.005 = 0.01 if added first, but each line rounds half up to 0.01.
    assert [row.kgs for row in report.kgs_rows] == [D("0.01"), D("0.01")]
    assert report.kgs_total == D("0.02")


# --- 13.2 who owes whom ------------------------------------------------------------------------


async def test_client_can_be_in_both_sections(session: AsyncSession, owner: User) -> None:
    ivan = await make_client(session, owner, "Иван")
    azamat = await make_client(session, owner, "Азамат")
    await adjust(session, owner, "10000")
    await record(session, owner, ivan, OperationType.LEND, "1000")
    await record(session, owner, ivan, OperationType.BORROW, "300")
    await record(session, owner, ivan, OperationType.BORROW, "20000", RUB)
    await record(session, owner, azamat, OperationType.LEND, "900")

    report = await data.debts_data(session, meta())

    assert [(s.currency, [(line.client, line.amount) for line in s.lines], s.total)
            for s in report.owed_to_you] == [
        (USD, [("Азамат", D("900")), ("Иван", D("700"))], D("1600")),
    ]  # fmt: skip
    assert [(s.currency, [(line.client, line.amount) for line in s.lines], s.total)
            for s in report.you_owe] == [
        (RUB, [("Иван", D("20000"))], D("20000")),
    ]  # fmt: skip


# --- 13.3 all records --------------------------------------------------------------------------


async def test_records_rows(session: AsyncSession, owner: User) -> None:
    clients = await scenarios_1_to_8(session, owner)
    wrong = await record(
        session, owner, clients["Азамат"], OperationType.LEND, "5", op_date=date(2026, 9, 5)
    )
    await reverse(session, owner, wrong, "ошибка")

    report = await data.records_data(session, meta(period=SEPTEMBER), SEPTEMBER)

    numbers = [row.number for row in report.rows]
    assert numbers == [1, 7, 2, 3, 4, 5, 6, 8]  # by date, then number
    by_number = {row.number: row for row in report.rows}
    paid_in_kgs = by_number[5]
    assert (paid_in_kgs.operation, paid_in_kgs.debt_amount, paid_in_kgs.debt_currency) == (
        "Мне вернули",
        D("600"),
        USD,
    )
    assert (paid_in_kgs.pay_amount, paid_in_kgs.pay_currency) == (D("52500"), KGS)
    assert paid_in_kgs.rate == "1 USD = 87,5 KGS"
    assert (by_number[1].pay_amount, by_number[1].rate, by_number[1].status) == (None, None, "")
    assert (by_number[7].status, by_number[7].grey) == ("отменена записью №8", True)
    assert (by_number[8].status, by_number[8].grey) == ("отмена записи №7 (ошибка)", True)
    assert by_number[1].author == "Владелец"
    assert by_number[1].created_at.tzinfo == ZONE


async def test_records_period_filter(session: AsyncSession, owner: User) -> None:
    await scenarios_1_to_8(session, owner)

    report = await data.records_data(session, meta(), Period(date(2026, 9, 10), date(2026, 9, 20)))

    assert [row.op_date.day for row in report.rows] == [10, 12, 20]


# --- 13.4 cash movements -----------------------------------------------------------------------


async def test_cash_movements_opening_and_closing(session: AsyncSession, owner: User) -> None:
    await scenarios_1_to_8(session, owner)
    await adjust(session, owner, "-500", USD, "Личные расходы", adj_date=date(2026, 9, 28))

    report = await data.cash_data(
        session,
        meta(period=Period(date(2026, 9, 5), date(2026, 9, 30))),
        Period(date(2026, 9, 5), date(2026, 9, 30)),
    )

    sections = {section.currency: section for section in report.sections}
    usd = sections[USD]
    assert usd.opening == D("9000")  # 10 000 adjusted and 1 000 lent before 05.09
    rows = [(r.number, r.description, r.income, r.expense, r.balance) for r in usd.rows]
    assert rows == [
        ("2", "Мне вернули — Азамат", D("400"), None, D("9400")),
        ("6", "Я вернул — Бекзат", None, D("300"), D("9100")),
        ("корр.", "Корректировка — Личные расходы", None, D("500"), D("8600")),
    ]
    assert usd.closing == D("8600")
    # EUR and KZT had no movement in the period but a non-zero balance: they are listed.
    assert (sections[EUR].opening, sections[EUR].rows, sections[EUR].closing) == (
        D("2000"),
        [],
        D("2000"),
    )
    assert list(sections) == [KGS, USD, EUR, RUB, KZT]


async def test_cash_movements_skip_currencies_without_anything(
    session: AsyncSession, owner: User
) -> None:
    await adjust(session, owner, "100", USD)

    report = await data.cash_data(session, meta(), Period())

    assert [section.currency for section in report.sections] == [USD]
    assert report.sections[0].opening == 0
    assert report.sections[0].closing == D("100")


# --- 13.5 statement ----------------------------------------------------------------------------


async def test_statement_opening_closing_and_running_balance(
    session: AsyncSession, owner: User
) -> None:
    clients = await scenarios_1_to_8(session, owner)
    period = Period(date(2026, 9, 5), date(2026, 9, 30))

    report = await data.statement_data(session, meta(period=period), period, clients["Азамат"].id)

    assert report.client == "Азамат"
    [usd] = report.sections
    assert usd.currency == USD
    assert usd.opening == D("1000")
    assert readable(data.balance_phrase(usd.opening, USD)) == "должен вам 1 000 USD"
    rows = [(r.number, r.operation, r.change, r.payment, r.balance) for r in usd.rows]
    assert [(*row[:3], row[3] and readable(row[3]), row[4]) for row in rows] == [
        (2, "Мне вернули", D("-400"), None, D("600")),
        (5, "Мне вернули", D("-600"), "52 500 KGS, курс 1 USD = 87,5 KGS", D("0")),
    ]
    assert usd.closing == 0
    assert data.balance_phrase(usd.closing, USD) == "долга нет"


async def test_statement_of_the_owners_debt(session: AsyncSession, owner: User) -> None:
    clients = await scenarios_1_to_8(session, owner)

    report = await data.statement_data(session, meta(), Period(), clients["Бекзат"].id)

    [rub] = report.sections
    assert rub.opening == 0
    assert [row.balance for row in rub.rows] == [D("-50000"), D("-30000"), D("-3000")]
    assert readable(data.balance_phrase(rub.closing, RUB)) == "вы должны 3 000 RUB"


# --- files -------------------------------------------------------------------------------------


def _cells(content: bytes, sheet: str) -> list[list[object]]:
    workbook = load_workbook(BytesIO(content))
    return [list(row) for row in workbook[sheet].iter_rows(values_only=True)]


async def test_summary_xlsx(session: AsyncSession, owner: User) -> None:
    await scenarios_1_to_8(session, owner)
    report = await data.summary_data(session, meta("Общая сводка"), SCENARIO_9_RATES)

    content = excel.summary_xlsx(report)

    workbook = load_workbook(BytesIO(content))
    assert workbook.sheetnames == ["Касса и долги", "Касса в сомах"]
    first = _cells(content, "Касса и долги")
    header = first.index(["Валюта", "В кассе", "Вам должны", "Вы должны", "Разница"])
    assert first[header + 4] == ["RUB", 530000, 0, 3000, -3000]
    sheet = workbook["Касса и долги"]
    assert sheet.freeze_panes == f"A{header + 2}"
    assert sheet.auto_filter.ref == f"A{header + 1}:E{header + 6}"
    assert sheet.cell(header + 2, 2).number_format == "#,##0.00"
    second = _cells(content, "Касса в сомах")
    assert second[-1][0] == "Итого"
    assert second[-1][3] == 2101750


async def test_records_xlsx_marks_cancelled_rows_grey(session: AsyncSession, owner: User) -> None:
    clients = await scenarios_1_to_8(session, owner)
    wrong = await record(session, owner, clients["Азамат"], OperationType.LEND, "5")
    await reverse(session, owner, wrong, "ошибка")
    report = await data.records_data(session, meta(period=SEPTEMBER), SEPTEMBER)

    content = excel.records_xlsx(report)

    sheet = load_workbook(BytesIO(content))["Записи"]
    rows = list(sheet.iter_rows(values_only=True))
    header = rows.index(tuple(
        ["№", "Дата", "Операция", "Клиент", "Сумма долга", "Валюта долга", "Оплата",
         "Валюта оплаты", "Курс", "Комментарий", "Автор", "Внесено", "Статус"]
    ))  # fmt: skip
    first = rows[header + 1]
    first_day = datetime(2026, 9, 1)  # noqa: DTZ001 (Excel dates are naive)
    assert first[:6] == (1, first_day, "Выдал в долг", "Азамат", 1000, "USD")
    by_number = {row[0]: (index, row) for index, row in enumerate(rows) if isinstance(row[0], int)}
    index, cancelled = by_number[wrong.id]
    assert cancelled[12] == f"отменена записью №{wrong.id + 1}"
    assert sheet.cell(index + 1, 1).fill.fgColor.rgb.endswith("D9D9D9")
    plain_index, _ = by_number[1]
    assert sheet.cell(plain_index + 1, 1).fill.fill_type is None


@pytest.mark.parametrize("kind", list(ReportKind))
async def test_every_report_renders_in_both_formats(
    session: AsyncSession, owner: User, kind: ReportKind
) -> None:
    clients = await scenarios_1_to_8(session, owner)
    for fmt in ReportFormat:
        result = await reports.build_report(
            session,
            kind,
            fmt,
            generated_by="Владелец",
            generated_at=NOW,
            period=SEPTEMBER,
            client_id=clients["Азамат"].id,
            rates=SCENARIO_9_RATES,
        )
        assert result.content
        if fmt == ReportFormat.PDF:
            assert result.content.startswith(b"%PDF")
            assert b"DejaVuSans" in result.content  # Cyrillic-capable font embedded
        else:
            load_workbook(BytesIO(result.content))


async def test_reports_on_an_empty_database(session: AsyncSession, owner: User) -> None:
    client = await make_client(session, owner, "Иван")
    for kind in ReportKind:
        for fmt in ReportFormat:
            result = await reports.build_report(
                session, kind, fmt, generated_by="Владелец", generated_at=NOW,
                period=Period(), client_id=client.id, rates={},
            )  # fmt: skip
            assert result.content


def test_pdf_splits_long_tables_into_numbered_pages() -> None:
    rows = [
        data.RecordRow(
            number=number,
            op_date=date(2026, 9, 1),
            operation="Выдал в долг",
            client="Клиент",
            debt_amount=D("1000"),
            debt_currency=USD,
            pay_amount=None,
            pay_currency=None,
            rate=None,
            comment="длинный комментарий " * 5,
            author="Владелец",
            created_at=NOW,
            status="",
            grey=number % 2 == 0,
        )
        for number in range(1, 200)
    ]

    content = pdf.records_pdf(data.RecordsReport(meta(period=SEPTEMBER), rows))

    assert content.startswith(b"%PDF")
    assert content.count(b"/Type /Page\n") > 3 or content.count(b"/Type /Page") > 3


@pytest.mark.parametrize(
    ("kind", "fmt", "period", "client", "expected"),
    [
        (ReportKind.SUMMARY, ReportFormat.XLSX, None, None, "Общая_сводка_2026-09-27.xlsx"),
        (ReportKind.DEBTS, ReportFormat.PDF, None, None, "Кто_кому_должен_2026-09-27.pdf"),
        (ReportKind.RECORDS, ReportFormat.PDF, SEPTEMBER, None, "Все_записи_2026-09-01_2026-09-30.pdf"),
        (ReportKind.CASH, ReportFormat.XLSX, Period(), None, "Движение_кассы_всё_время.xlsx"),
        (ReportKind.STATEMENT, ReportFormat.PDF, SEPTEMBER, "Иван (Ош)", "Выписка_Иван_(Ош)_2026-09-01_2026-09-30.pdf"),
        (ReportKind.STATEMENT, ReportFormat.XLSX, SEPTEMBER, "a/b\\\\c", "Выписка_a_b_c_2026-09-01_2026-09-30.xlsx"),
    ],
)  # fmt: skip
def test_file_names(
    kind: ReportKind, fmt: ReportFormat, period: Period | None, client: str | None, expected: str
) -> None:
    assert reports.file_name(kind, fmt, NOW, period, client) == expected
