"""«Кто кому должен», «Журнал записей», «Движение балансов» and «Выписка по клиенту» through
the bot (TZ 13.10, 14)."""

from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import User
from app.services import days
from tests.bot.harness import UserClient
from tests.services.accounting import DAY_1_RATES, acceptance_day_1

MOSCOW = ZoneInfo("Europe/Moscow")
BACK_ROW = [texts.BTN_BACK, texts.BTN_HOME]


def last_document(client: UserClient) -> tuple[str, bytes]:
    message = next(m for m in reversed(client.bot_messages) if m.document_name is not None)
    assert message.document_name is not None
    assert message.document_data is not None
    return message.document_name, message.document_data


async def open_report(client: UserClient, button: str) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_REPORTS)
    await client.click(button)


async def test_who_owes_whom(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await acceptance_day_1(session, owner_user)
    await open_report(owner_client, texts.BTN_WHO_OWES)
    assert owner_client.last.text == f"Кто кому должен\n\n{texts.CHOOSE_FORMAT}"
    screen = owner_client.last

    await owner_client.click(texts.BTN_EXCEL)
    await owner_client.click(texts.BTN_PDF, message=screen)

    names = [m.document_name for m in owner_client.bot_messages if m.document_name]
    assert [name.split("_2")[0] for name in names] == ["Кто_кому_должен"] * 2
    assert (names[0][-5:], names[1][-4:]) == (".xlsx", ".pdf")
    book = load_workbook(BytesIO(owner_client.bot_messages[-2].document_data or b""))
    rows = list(book["По обменам"].iter_rows(values_only=True))
    assert ("USD", "Мы должны", "Азамат", 1000) in rows


async def test_journal_of_the_current_day(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await acceptance_day_1(session, owner_user)
    await open_report(owner_client, texts.BTN_JOURNAL)
    assert owner_client.last.text == "Журнал записей\n\nЗа какой период?"
    assert owner_client.last.buttons == [
        [texts.BTN_CURRENT_DAY],
        [texts.BTN_CLOSED_DAY],
        [texts.BTN_DATES],
        BACK_ROW,
    ]

    await owner_client.click(texts.BTN_CURRENT_DAY)
    assert owner_client.last.text == f"Журнал записей\nДень №1 (открыт)\n\n{texts.CHOOSE_FORMAT}"
    await owner_client.click(texts.BTN_EXCEL)

    name, data = last_document(owner_client)
    assert name.startswith("Журнал_день_1_")
    rows = list(load_workbook(BytesIO(data))["Журнал"].iter_rows(values_only=True))
    assert [row[0] for row in rows if isinstance(row[0], int)] == [1, 2, 3, 4, 5, 6]


async def test_movement_of_a_closed_day(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_report(owner_client, texts.BTN_MOVEMENT)
    assert await owner_client.click(texts.BTN_CLOSED_DAY) == texts.NO_CLOSED_DAYS
    await acceptance_day_1(session, owner_user)
    await days.close_day(session, owner_user, 1, DAY_1_RATES)
    closed = await days.archived_report(session, 1)
    assert closed[0].closed_at is not None
    closed_on = closed[0].closed_at.astimezone(MOSCOW)

    await owner_client.click(texts.BTN_CLOSED_DAY)
    assert owner_client.last.text.endswith(texts.ASK_CLOSED_DAY)
    await owner_client.click(f"День №1 · {closed_on:%d.%m.%Y} · +1 053,50")
    assert owner_client.last.text == (
        f"Движение балансов\nДень №1 · закрыт {closed_on:%d.%m.%Y}\n\n{texts.CHOOSE_FORMAT}"
    )
    await owner_client.click(texts.BTN_PDF)

    name, data = last_document(owner_client)
    assert name.startswith("Движение_балансов_день_1_")
    assert data.startswith(b"%PDF")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.endswith(texts.ASK_CLOSED_DAY)


async def test_journal_by_dates(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await acceptance_day_1(session, owner_user)
    today = datetime.now(MOSCOW).date()
    await open_report(owner_client, texts.BTN_JOURNAL)
    await owner_client.click(texts.BTN_DATES)
    assert owner_client.last.text == f"Журнал записей\n\n{texts.ASK_START_DATE}"

    await owner_client.send("2026-10-01")
    assert texts.INVALID_DATE in owner_client.last.text
    await owner_client.send(f"{today:%d.%m.%Y}")
    assert owner_client.last.text == (f"Журнал записей\nС {today:%d.%m.%Y}\n\n{texts.ASK_END_DATE}")
    await owner_client.send("01.01.2000")
    assert texts.END_BEFORE_START in owner_client.last.text
    await owner_client.send(f"{today:%d.%m.%Y}")
    assert owner_client.last.text == (
        f"Журнал записей\nДата: {today:%d.%m.%Y}\n\n{texts.CHOOSE_FORMAT}"
    )
    await owner_client.click(texts.BTN_EXCEL)

    name, data = last_document(owner_client)
    assert name == f"Журнал_{today:%Y-%m-%d}.xlsx"
    rows = list(load_workbook(BytesIO(data))["Журнал"].iter_rows(values_only=True))
    assert len([row for row in rows if isinstance(row[0], int)]) == 6

    screens = []
    for _ in range(4):
        await owner_client.click(texts.BTN_BACK)
        screens.append(owner_client.last.text.splitlines()[-1])
    assert screens == [
        texts.ASK_END_DATE,
        texts.ASK_START_DATE,
        texts.ASK_PERIOD,
        "Отчёты",
    ]


async def test_statement_from_the_reports(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await acceptance_day_1(session, owner_user)
    await open_report(owner_client, texts.BTN_STATEMENT_REPORT)
    assert texts.BTN_NEW_CLIENT not in owner_client.last.button_texts  # decision 17

    await owner_client.click("Бекзат")
    assert owner_client.last.text == "Выписка по клиенту\nКлиент: Бекзат\n\nЗа какой период?"
    assert owner_client.last.buttons == [[texts.BTN_ALL_TIME], [texts.BTN_DATES], BACK_ROW]
    await owner_client.click(texts.BTN_ALL_TIME)
    assert owner_client.last.text == (
        f"Выписка по клиенту\nКлиент: Бекзат\nВсё время\n\n{texts.CHOOSE_FORMAT}"
    )
    await owner_client.click(texts.BTN_EXCEL)

    name, data = last_document(owner_client)
    assert name.startswith("Выписка_Бекзат_всё_время_")
    book = load_workbook(BytesIO(data))
    assert book.sheetnames == ["Долг в сомах"]
    await owner_client.click(texts.BTN_BACK)
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.endswith(texts.CHOOSE_CLIENT_HINT)
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == "Отчёты"


async def test_statement_from_the_client_card(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await acceptance_day_1(session, owner_user)
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CLIENTS)
    await owner_client.click("Азамат")

    await owner_client.click(texts.BTN_STATEMENT)
    assert owner_client.last.text == "Выписка по клиенту\nКлиент: Азамат\n\nЗа какой период?"
    await owner_client.click(texts.BTN_ALL_TIME)
    await owner_client.click(texts.BTN_PDF)
    name, _ = last_document(owner_client)
    assert name.startswith("Выписка_Азамат_всё_время_")

    await owner_client.click(texts.BTN_BACK)
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.startswith("Азамат\n\nПо обменам:")
