"""«Кто кому должен», the journal, the movement of balances and the statement
(TZ 14; 18: «Отчёты» on the state after the acceptance scenarios)."""

from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, User
from app.domain.day_report import ExchangeList, NameLine
from app.domain.entries import Book, OperationType
from app.services import days, reports
from app.services.reports.data import (
    Period,
    ReportFormat,
    ReportMeta,
    journal_data,
    movement_data,
    statement_data,
    who_owes_data,
)
from tests.factories import make_client, make_loan
from tests.services.accounting import (
    DAY_1_RATES,
    DAY_2_RATES,
    KGS,
    RUB,
    USD,
    D,
    acceptance_day_1,
    acceptance_day_2,
    acceptance_day_3,
)

MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 3, 18, 5, tzinfo=MOSCOW)
META = ReportMeta("Отчёт", NOW, "Владелец")
XLSX, PDF = ReportFormat.XLSX, ReportFormat.PDF


@pytest.fixture
async def three_days(session: AsyncSession, owner: User, helper: User) -> dict[str, Client]:
    """TZ 17.1, scenarios 1-14: day №1 and №2 closed, day №3 open."""
    await days.ensure_open_day(session)
    people = await acceptance_day_1(session, owner)
    await days.close_day(session, owner, 1, DAY_1_RATES)
    await acceptance_day_2(session, owner, people["Азамат"])
    await days.close_day(session, owner, 2, DAY_2_RATES)
    people["Тимур"] = await acceptance_day_3(session, owner, helper, people["Бекзат"])
    return people


def lines(*items: tuple[str, str]) -> list[NameLine]:
    return [NameLine(name, D(amount)) for name, amount in items]


async def test_who_owes_whom_after_day_1(session: AsyncSession, owner: User) -> None:
    await days.ensure_open_day(session)
    await acceptance_day_1(session, owner)

    data = await who_owes_data(session, META)

    assert data.exchanges == [ExchangeList(USD, [], lines(("Азамат", "1000")))]
    assert data.loans == ExchangeList(KGS, lines(("Бекзат", "50000")), [])


async def test_nobody_owes_anything_after_day_3(
    session: AsyncSession, three_days: dict[str, Client]
) -> None:
    data = await who_owes_data(session, META)

    assert (data.exchanges, data.loans) == ([], ExchangeList(KGS, [], []))


async def test_journal_of_day_3(session: AsyncSession, three_days: dict[str, Client]) -> None:
    data = await journal_data(session, META, Period(day_id=3), MOSCOW)

    rows = {row.number: row for row in data.records}
    assert list(rows) == [9, 10, 11, 12, 13]
    assert rows[9].gives is not None
    assert (rows[9].gives.amount, rows[9].gives.currency) == (D("100000"), RUB)
    assert rows[10].execution == "выдано, оплата позже"
    assert (rows[11].author, rows[11].status, rows[11].grey) == (
        "Айгуль",
        "отменена записью №12",
        True,
    )
    assert (rows[12].status, rows[12].grey) == ("отмена записи №11 (ошибка в сумме)", True)
    assert (rows[13].status, rows[13].grey) == ("", False)


async def test_journal_by_dates_takes_every_day(
    session: AsyncSession, three_days: dict[str, Client]
) -> None:
    today = datetime.now(MOSCOW).date()

    data = await journal_data(session, META, Period(start=today, end=today), MOSCOW)

    assert [row.number for row in data.records] == list(range(1, 14))


async def test_movement_of_day_2(session: AsyncSession, three_days: dict[str, Client]) -> None:
    data = await movement_data(session, META, Period(day_id=2), MOSCOW)

    blocks = {block.currency: block for block in data.blocks}
    assert list(blocks) == [USD, RUB, KGS]  # EUR and KZT neither moved nor hold anything
    usd = blocks[USD]
    assert (usd.start, usd.end) == (D("10000"), D("11000"))
    assert [(row.number, row.incoming, row.outgoing, row.balance) for row in usd.rows] == [
        (7, None, D("1000"), D("9000")),
        (8, D("2000"), None, D("11000")),
    ]
    assert usd.rows[0].description == "Выдача по обмену · Азамат · 1\u00a0000 USD"
    assert (blocks[RUB].start, blocks[RUB].rows, blocks[RUB].end) == (
        D("88500"),
        [],
        D("88500"),
    )
    assert (blocks[KGS].start, blocks[KGS].end) == (D("951000"), D("776000"))


async def test_movement_of_day_3_shows_the_cancellation_in_grey(
    session: AsyncSession, three_days: dict[str, Client]
) -> None:
    data = await movement_data(session, META, Period(day_id=3), MOSCOW)

    som = next(block for block in data.blocks if block.currency == KGS)
    assert [(row.number, row.balance, row.grey) for row in som.rows] == [
        (10, D("677990"), False),
        (11, D("682990"), True),
        (12, D("677990"), True),
        (13, D("727990"), False),
    ]
    assert som.end == D("727990")


async def test_statement_of_timur_nets_the_rubles(
    session: AsyncSession, three_days: dict[str, Client]
) -> None:
    data = await statement_data(session, META, Period(), MOSCOW, three_days["Тимур"])

    (block,) = data.blocks
    assert (block.book, block.currency, block.start, block.end) == (
        Book.EXCHANGE,
        RUB,
        0,
        0,
    )
    assert [(row.number, row.change, row.after) for row in block.rows] == [
        (9, D("-99000"), D("-99000")),
        (10, D("99000"), 0),
    ]


async def test_statement_of_bekzat(session: AsyncSession, three_days: dict[str, Client]) -> None:
    data = await statement_data(session, META, Period(), MOSCOW, three_days["Бекзат"])

    (block,) = data.blocks
    assert (block.book, block.currency) == (Book.LOAN, KGS)
    assert [(row.number, row.after, row.grey) for row in block.rows] == [
        (6, D("50000"), False),
        (11, D("45000"), True),
        (12, D("50000"), True),
        (13, 0, False),
    ]
    assert block.rows[0].operation == "Выдал в долг · 50 000 KGS"


async def test_periods_by_dates_count_what_was_before(session: AsyncSession, owner: User) -> None:
    await days.ensure_open_day(session)
    ivan = await make_client(session, owner, "Иван")

    def at(day: int, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 10, day, hour, minute, tzinfo=MOSCOW)

    await make_loan(session, owner, ivan, "1000", created_at=at(1, 10))
    await make_loan(session, owner, ivan, "500", created_at=at(2, 0, 0))
    await make_loan(session, owner, ivan, "200", created_at=at(2, 23, 59))
    await make_loan(session, owner, ivan, "70", OperationType.LOAN_REPAY_IN, created_at=at(3, 0))
    period = Period(start=date(2026, 10, 2), end=date(2026, 10, 2))

    statement = await statement_data(session, META, period, MOSCOW, ivan)
    movement = await movement_data(session, META, period, MOSCOW)

    (block,) = statement.blocks
    assert (block.start, [row.change for row in block.rows], block.end) == (
        D("1000"),
        [D("500"), D("200")],
        D("1700"),
    )
    (som,) = movement.blocks
    assert (som.start, som.end) == (D("-1000"), D("-1700"))  # the factory skips the cash rule


async def test_files_of_the_reports(session: AsyncSession, three_days: dict[str, Client]) -> None:
    kwargs = {"generated_by": "Владелец", "generated_at": NOW, "zone": MOSCOW}

    who = await reports.who_owes_file(session, XLSX, **kwargs)
    journal = await reports.journal_file(session, Period(day_id=3), PDF, **kwargs)
    movement = await reports.movement_file(
        session, Period(start=date(2026, 10, 1), end=date(2026, 10, 3)), XLSX, **kwargs
    )
    statement = await reports.statement_file(
        session, three_days["Тимур"].id, Period(), XLSX, **kwargs
    )

    assert [who.filename, journal.filename, movement.filename, statement.filename] == [
        "Кто_кому_должен_2026-10-03_1805.xlsx",
        "Журнал_день_3_2026-10-03_1805.pdf",
        "Движение_балансов_2026-10-01_2026-10-03.xlsx",
        "Выписка_Тимур_всё_время_2026-10-03.xlsx",
    ]
    assert journal.content.startswith(b"%PDF")
    book = load_workbook(BytesIO(who.content))
    assert book.sheetnames == ["По обменам", "Долги в сомах"]
    assert book["По обменам"]["A2"].value == "На 03.10.2026 18:05"
    sheets = load_workbook(BytesIO(statement.content))
    assert sheets.sheetnames == ["Обмены RUB"]
    rows = list(sheets["Обмены RUB"].iter_rows(values_only=True))
    assert rows[5][:1] == ("Остаток на начало: обязательств нет",)
    changes = [row[3] for row in rows if isinstance(row[1], int)]
    assert changes == [-99000, 99000]
    assert rows[-1][0] == "Остаток на конец"
    assert rows[-1][4] == "обязательств нет"


@pytest.mark.parametrize("fmt", [XLSX, PDF])
async def test_every_report_renders_in_both_formats(
    session: AsyncSession, three_days: dict[str, Client], fmt: ReportFormat
) -> None:
    kwargs = {"generated_by": "Владелец", "generated_at": NOW, "zone": MOSCOW}
    files = [
        await reports.who_owes_file(session, fmt, **kwargs),
        await reports.journal_file(session, Period(), fmt, **kwargs),
        await reports.movement_file(session, Period(day_id=1), fmt, **kwargs),
        await reports.statement_file(session, three_days["Бекзат"].id, Period(), fmt, **kwargs),
    ]

    for file in files:
        assert file.filename.endswith(f".{fmt}")
        assert len(file.content) > 1000
