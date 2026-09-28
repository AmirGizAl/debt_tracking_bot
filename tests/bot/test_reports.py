"""Reports through the bot UI (TZ 12.8; scenario 9)."""

from datetime import date
from io import BytesIO

import pytest
from aiogram.enums import ChatAction
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import RepAction, RepCb
from app.bot.handlers import reports as handlers
from app.db.models import User
from app.domain.currency import Currency
from app.domain.dates import today
from app.services import users
from tests.bot.harness import Harness, UserClient
from tests.bot.records import TZ
from tests.services.accounting import adjust, scenarios_1_to_8


async def open_report(client: UserClient, button: str) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_REPORTS)
    assert client.last.text == texts.REPORTS_TITLE
    await client.click(button)


def last_document(client: UserClient) -> tuple[str, bytes]:
    documents = [m for m in client.bot_messages if m.document_name is not None]
    assert documents, "no file was sent"
    message = documents[-1]
    assert message.document_data is not None
    return message.document_name or "", message.document_data


async def test_scenario_9_summary(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await scenarios_1_to_8(session, owner_user)
    await open_report(owner_client, texts.BTN_REPORT_SUMMARY)

    questions = []
    for rate in ("87,5", "100", "1,1", "0,17"):
        questions.append(owner_client.last.text.splitlines()[-1])
        await owner_client.send(rate)
    assert questions == [
        "Сколько сомов за 1 USD?",
        "Сколько сомов за 1 EUR?",
        "Сколько сомов за 1 RUB?",
        "Сколько сомов за 1 KZT?",
    ]
    assert owner_client.last.text.endswith(texts.ASK_FORMAT)
    await owner_client.click(texts.BTN_EXCEL)

    name, content = last_document(owner_client)
    assert name == f"Общая_сводка_{today(TZ).isoformat()}.xlsx"
    rows = list(load_workbook(BytesIO(content))["Касса в сомах"].iter_rows(values_only=True))
    assert rows[-1][0] == "Итого"
    assert rows[-1][3] == 2101750
    assert owner_client.bot_messages[-1].text == texts.MAIN_MENU
    assert any(
        action.action == ChatAction.UPLOAD_DOCUMENT for action in harness.telegram.chat_actions
    )


async def test_summary_skips_rates_without_foreign_cash(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "1000", Currency.KGS)

    await open_report(owner_client, texts.BTN_REPORT_SUMMARY)

    assert owner_client.last.text.endswith(texts.ASK_FORMAT)
    await owner_client.click(texts.BTN_PDF)
    name, content = last_document(owner_client)
    assert name.endswith(".pdf")
    assert content.startswith(b"%PDF")


async def test_wrong_rate_is_asked_again(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await adjust(session, owner_user, "100", Currency.USD)
    await open_report(owner_client, texts.BTN_REPORT_SUMMARY)

    await owner_client.send("ноль")

    assert owner_client.last.text.startswith(texts.RATE_ERRORS[texts.NumberProblem.FORMAT])
    assert owner_client.last.text.endswith("Сколько сомов за 1 USD?")


async def test_debts_report(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await scenarios_1_to_8(session, owner_user)
    await open_report(owner_client, texts.BTN_REPORT_DEBTS)
    await owner_client.click(texts.BTN_EXCEL)

    name, content = last_document(owner_client)
    assert name == f"Кто_кому_должен_{today(TZ).isoformat()}.xlsx"
    rows = list(load_workbook(BytesIO(content))["Вы должны"].iter_rows(values_only=True))
    assert ("RUB", "Бекзат", 3000) in rows


async def test_period_buttons(owner_client: UserClient) -> None:
    # Customer's request of 28.09.2026: the last N days, no dates to type.
    await open_report(owner_client, texts.BTN_REPORT_RECORDS)

    assert owner_client.last.text == f"{texts.REPORT_TITLES['records']}\n{texts.ASK_PERIOD}"
    assert owner_client.last.buttons == [
        [texts.BTN_PERIOD_TODAY, texts.BTN_PERIOD_WEEK],
        [texts.BTN_PERIOD_MONTH, texts.BTN_PERIOD_YEAR],
        [texts.BTN_ALL_TIME],
        [texts.BTN_BACK, texts.BTN_HOME],
    ]


async def test_records_report_for_today(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await scenarios_1_to_8(session, owner_user)
    await open_report(owner_client, texts.BTN_REPORT_RECORDS)

    await owner_client.click(texts.BTN_PERIOD_TODAY)
    await owner_client.click(texts.BTN_EXCEL)

    current = today(TZ)
    name, content = last_document(owner_client)
    assert name == f"Все_записи_{current.isoformat()}.xlsx"
    rows = list(load_workbook(BytesIO(content))["Записи"].iter_rows(values_only=True))
    assert (f"Период: {current:%d.%m.%Y}",) == rows[1][:1]


async def test_cash_report_for_a_week(
    owner_client: UserClient,
    session: AsyncSession,
    owner_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(handlers, "today", lambda zone: date(2026, 9, 27))
    await scenarios_1_to_8(session, owner_user)
    await open_report(owner_client, texts.BTN_REPORT_CASH)

    await owner_client.click(texts.BTN_PERIOD_WEEK)
    await owner_client.click(texts.BTN_EXCEL)

    name, content = last_document(owner_client)
    assert name == "Движение_кассы_2026-09-21_2026-09-27.xlsx"
    usd = list(load_workbook(BytesIO(content))["USD"].iter_rows(values_only=True))
    assert ("Остаток на начало", None, None, None, None, 9400) in usd  # 10.09 is before it
    assert ("Остаток на конец", None, None, None, None, 9100) in usd  # 300 USD paid on 27.09


async def test_period_button_of_the_old_version(owner_client: UserClient) -> None:
    # A period screen left open while the bot was updated still has the old buttons.
    await open_report(owner_client, texts.BTN_REPORT_RECORDS)
    screen = owner_client.last

    popup = await owner_client.press(RepCb(action=RepAction.PERIOD, value="custom").pack(), screen)

    assert popup.text == texts.STALE_ACTION
    assert owner_client.last.text.endswith(texts.ASK_PERIOD)
    await owner_client.click(texts.BTN_ALL_TIME)
    assert owner_client.last.text.endswith(texts.ASK_FORMAT)


async def test_statement_from_client_card(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await scenarios_1_to_8(session, owner_user)
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CLIENTS)
    await owner_client.click("Азамат")
    await owner_client.click(texts.BTN_STATEMENT)
    assert owner_client.last.text == (
        f"{texts.REPORT_TITLES['statement']}\nКлиент: Азамат\n{texts.ASK_PERIOD}"
    )

    await owner_client.click(texts.BTN_ALL_TIME)
    await owner_client.click(texts.BTN_EXCEL)

    name, content = last_document(owner_client)
    assert name == "Выписка_Азамат_всё_время.xlsx"
    usd = list(load_workbook(BytesIO(content))["USD"].iter_rows(values_only=True))
    closing = [row for row in usd if row[0] == "Остаток на конец"]
    assert closing == [("Остаток на конец", None, "долга нет", None, None, 0)]


async def test_statement_client_choice_and_back(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await scenarios_1_to_8(session, owner_user)
    await open_report(owner_client, texts.BTN_REPORT_STATEMENT)
    assert owner_client.last.text.startswith(texts.STATEMENT_CLIENT_QUESTION)
    assert texts.BTN_NEW_CLIENT not in owner_client.last.button_texts  # no creating here

    await owner_client.send("бек")
    await owner_client.click("Бекзат")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text.startswith(texts.STATEMENT_CLIENT_QUESTION)
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == texts.REPORTS_TITLE


async def test_helper_can_build_reports(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await users.add_helper(session, owner_user, "aigul_k")
    helper = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await helper.send("/start")
    await open_report(helper, texts.BTN_REPORT_DEBTS)
    await helper.click(texts.BTN_PDF)

    name, _ = last_document(helper)
    assert name.startswith("Кто_кому_должен_")


@pytest.mark.parametrize(
    ("button", "expected"),
    [
        (texts.BTN_PERIOD_TODAY, "Все_записи_{today}.xlsx"),
        (texts.BTN_PERIOD_WEEK, "Все_записи_2026-09-21_{today}.xlsx"),
        (texts.BTN_PERIOD_MONTH, "Все_записи_2026-08-29_{today}.xlsx"),
        (texts.BTN_PERIOD_YEAR, "Все_записи_2025-09-28_{today}.xlsx"),
        (texts.BTN_ALL_TIME, "Все_записи_всё_время.xlsx"),
    ],
)
async def test_period_presets(
    owner_client: UserClient,
    monkeypatch: pytest.MonkeyPatch,
    button: str,
    expected: str,
) -> None:
    monkeypatch.setattr(handlers, "today", lambda zone: date(2026, 9, 27))
    await open_report(owner_client, texts.BTN_REPORT_RECORDS)
    await owner_client.click(button)
    await owner_client.click(texts.BTN_EXCEL)

    name, _ = last_document(owner_client)
    assert name == expected.format(today="2026-09-27")
