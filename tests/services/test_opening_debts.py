"""Opening debts: debts from before the bot (agreed with the customer on 03.10.2026)."""

import asyncio
import uuid
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Client, Operation, User
from app.domain.currency import Currency
from app.domain.entries import Book, OperationType
from app.domain.errors import OpeningDebtExists, PermissionDenied
from app.services import days, ledger, obligations, opening_debts, reports
from app.services.reports.data import ReportFormat
from tests.factories import make_client
from tests.services.accounting import (
    KGS,
    RUB,
    USD,
    D,
    cancel,
    force_close_day,
    open_balance,
    settle,
    swap,
)

EXCHANGE, LOAN = Book.EXCHANGE, Book.LOAN
MOSCOW = ZoneInfo("Europe/Moscow")


async def debt(
    session: AsyncSession,
    actor: User,
    client: Client,
    amount: str,
    currency: Currency = USD,
    book: Book = EXCHANGE,
) -> Operation:
    record, _ = await opening_debts.create_opening_debt(
        session, actor, uuid.uuid4(), client.id, book, currency, D(amount)
    )
    return record


@pytest.fixture
async def azamat(session: AsyncSession, owner: User) -> Client:
    await days.ensure_open_day(session)
    return await make_client(session, owner, "Азамат")


async def test_opening_debt_moves_no_money(
    session: AsyncSession, owner: User, azamat: Client
) -> None:
    await open_balance(session, owner, "10000", USD)

    record = await debt(session, owner, azamat, "-1000")  # we owe Азамат 1 000 USD

    assert record.type == OperationType.OPENING_DEBT
    assert await ledger.balance(session, USD) == D("10000")
    assert await ledger.client_obligations(session, azamat.id) == {(EXCHANGE, USD): D("-1000")}
    waiting = await obligations.waiting(session, paying=True)
    assert [(line.client, line.amount) for line in waiting] == [("Азамат", D("-1000"))]


async def test_som_debt_goes_to_the_book_chosen(
    session: AsyncSession, owner: User, azamat: Client
) -> None:
    loan = await debt(session, owner, azamat, "50000", KGS, LOAN)
    exchange = await debt(session, owner, azamat, "-3000", KGS, EXCHANGE)  # another book

    assert (loan.type, exchange.type) == (OperationType.OPENING_LOAN, OperationType.OPENING_DEBT)
    assert await ledger.client_obligations(session, azamat.id) == {
        (EXCHANGE, KGS): D("-3000"),
        (LOAN, KGS): D("50000"),
    }
    assert [line.client for line in await obligations.loan_debts(session)] == ["Азамат"]
    assert await ledger.balance(session, KGS) == 0


async def test_only_owners_enter_opening_debts(
    session: AsyncSession, helper: User, azamat: Client
) -> None:
    with pytest.raises(PermissionDenied):
        await debt(session, helper, azamat, "100")


async def test_one_debt_per_client_book_and_currency(
    session: AsyncSession, owner: User, azamat: Client
) -> None:
    first = await debt(session, owner, azamat, "100")

    with pytest.raises(OpeningDebtExists):
        await debt(session, owner, azamat, "-50")
    await debt(session, owner, azamat, "70", RUB)  # another currency is fine
    await cancel(session, owner, first, "не та сумма")
    await debt(session, owner, azamat, "150")  # after the cancellation the currency is free

    listed = await opening_debts.active_debts(session)
    assert [(d.client, d.currency, d.amount) for d in listed] == [
        ("Азамат", RUB, D("70")),
        ("Азамат", USD, D("150")),
    ]


async def test_any_day_entering_and_cancelling(
    session: AsyncSession, owner: User, azamat: Client
) -> None:
    # Agreed on 03.10.2026: unlike the opening balances, debts are not frozen by a closing.
    await force_close_day(session, owner)

    record = await debt(session, owner, azamat, "100")
    await force_close_day(session, owner)
    cancellation = await cancel(session, owner, record, "клиент уже вернул")

    assert cancellation.day_id == 3
    assert await ledger.client_obligations(session, azamat.id) == {}


async def test_parallel_entering_saves_one(
    sessionmaker: async_sessionmaker[AsyncSession], owner: User, azamat: Client
) -> None:
    async def enter() -> str:
        async with sessionmaker() as own:
            try:
                await debt(own, owner, azamat, "100")
            except OpeningDebtExists:
                return "refused"
            return "saved"

    assert sorted(await asyncio.gather(enter(), enter())) == ["refused", "saved"]


async def test_opening_debts_are_a_part_of_the_starting_point(
    session: AsyncSession, owner: User, azamat: Client
) -> None:
    bekzat = await make_client(session, owner, "Бекзат")
    await open_balance(session, owner, "10000", USD)
    await open_balance(session, owner, "1000000", KGS)
    await debt(session, owner, azamat, "1000")  # Азамат owes us 1 000 USD from before
    await debt(session, owner, bekzat, "-20000", KGS, LOAN)  # we owe Бекзат 20 000 som

    _, report = await days.preliminary_report(session, {USD: D("87.65")})
    # 10 000 × 87,65 + 1 000 × 87,65 + 1 000 000 − 20 000, both in the total and the baseline.
    assert (report.total, report.baseline_total, report.surplus) == (
        D("1944150"),
        D("1944150"),
        0,
    )

    # Азамат pays the old debt: the money replaces the debt, no profit appears.
    await settle(session, owner, OperationType.EXCHANGE_RECEIPT, azamat, "1000", USD)
    _, report = await days.preliminary_report(session, {USD: D("87.65")})
    assert report.surplus == 0

    # Some of the money goes out at a better rate: that is a real profit.
    await swap(session, owner, "88000", KGS, "1000", USD, rate="88")
    _, report = await days.preliminary_report(session, {USD: D("87.65")})
    assert report.surplus == Decimal("350")


async def test_report_file_shows_the_opening_debts(
    session: AsyncSession, owner: User, azamat: Client
) -> None:
    await open_balance(session, owner, "10000", USD)
    await debt(session, owner, azamat, "-1000")
    now = datetime(2026, 10, 3, 18, 5, tzinfo=MOSCOW)

    report = await reports.preliminary_file(
        session, {USD: D("87.65")}, ReportFormat.XLSX, generated_by="Владелец",
        generated_at=now, zone=MOSCOW,
    )  # fmt: skip

    rows = list(load_workbook(BytesIO(report.content))["Отчёт"].iter_rows(values_only=True))
    labels = {row[0]: row[1] for row in rows if isinstance(row[0], str)}
    assert labels["· USD: 10 000 × 87,65"] == 876500
    assert labels["· долги USD: −1 000 × 87,65"] == -87650
    assert labels["Начальная точка"] == 788850
    assert labels["Излишки"] == 0
    journal = list(load_workbook(BytesIO(report.content))["Записи дня"].iter_rows(values_only=True))
    debt_row = next(row for row in journal if row[0] == 2)
    assert (debt_row[3], debt_row[4], debt_row[9]) == ("Начальный долг по обменам", "Азамат", -1000)
