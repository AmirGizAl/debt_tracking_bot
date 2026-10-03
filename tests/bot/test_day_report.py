"""The preliminary report, the closing of the day and the archive through the bot
(TZ 7.2, 8.2, 8.3, 8.5, 13.9, 13.10; scenarios 7, 8, 11)."""

from datetime import date
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb
from app.config import Settings
from app.db.models import BusinessDay, DayStatus, User
from app.services import days, users
from tests.bot.harness import FakeMessage, Harness, UserClient
from tests.conftest import SECOND_OWNER_TG_ID
from tests.services.accounting import (
    DAY_1_RATES,
    KGS,
    RUB,
    USD,
    D,
    acceptance_day_1,
    acceptance_day_2,
    adjust,
    open_balance,
    swap,
)

GROUP = -1001234567890
MOSCOW = ZoneInfo("Europe/Moscow")
DAY_1_CHECK = [
    "USD: 10 000 + 0 − 1 000 = 9 000 × 87,65 = 788 850",
    "RUB: 88 500 + 0 − 0 = 88 500 × 0,991 = 87 703,50",
    "Наличка: 951 000",
    "Долги в сомах: нам 50 000, мы 0",
    "",
    "Итог: 1 877 553,50",
    "Начальная точка: 1 876 500",
    "Излишки: +1 053,50",
    "Изменение за день: +1 053,50",
]


def documents(messages: list[FakeMessage]) -> list[str]:
    return [m.document_name for m in messages if m.document_name is not None]


async def closed_on(session: AsyncSession, day_id: int) -> date:
    day = await session.get(BusinessDay, day_id, populate_existing=True)
    assert day is not None
    assert day.closed_at is not None
    return day.closed_at.astimezone(MOSCOW).date()


async def enter_rates(client: UserClient, *rates: str) -> None:
    for rate in rates:
        await client.send(rate)


async def start_closing(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_CLOSE_DAY)


async def start_preliminary(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_REPORTS)
    await client.click(texts.BTN_PRELIMINARY)


async def test_reports_screen(owner_client: UserClient) -> None:
    await owner_client.send("/menu")

    await owner_client.click(texts.BTN_REPORTS)

    assert owner_client.last.text == "Отчёты"
    assert owner_client.last.buttons == [
        [texts.BTN_PRELIMINARY],
        [texts.BTN_ARCHIVE],
        [texts.BTN_WHO_OWES],
        [texts.BTN_JOURNAL],
        [texts.BTN_MOVEMENT],
        [texts.BTN_STATEMENT_REPORT],
        [texts.BTN_HOME],
    ]


async def test_scenario_7_preliminary_report(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await acceptance_day_1(session, owner_user)
    await users.add_helper(session, owner_user, "aigul_k")
    aigul = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await aigul.send("/start")  # any user may take a preliminary report (TZ 8.3)

    await aigul.click(texts.BTN_REPORTS)
    await aigul.click(texts.BTN_PRELIMINARY)
    assert aigul.last.text == "Предварительный отчёт · день №1\n\nСколько сомов за 1 USD?"
    assert aigul.last.buttons == [[texts.BTN_BACK, texts.BTN_HOME]]  # no closed day yet
    await aigul.send("87,65")
    assert aigul.last.text == (
        "Предварительный отчёт · день №1\nКурсы: USD 87,65\n\nСколько сомов за 1 RUB?"
    )
    await aigul.send("0,991")

    lines = aigul.last.text.splitlines()
    assert lines[0].startswith("Предварительный отчёт · день №1 · ")
    assert lines[1:] == [*DAY_1_CHECK, "", texts.CHOOSE_FORMAT]
    assert aigul.last.buttons == [
        [texts.BTN_EXCEL, texts.BTN_PDF],
        [texts.BTN_CHANGE_RATES],
        [texts.BTN_BACK, texts.BTN_HOME],
    ]
    screen = aigul.last
    await aigul.click(texts.BTN_EXCEL)
    await aigul.click(texts.BTN_PDF, message=screen)  # the screen stays for the other format
    names = documents(aigul.bot_messages)
    assert len(names) == 2
    assert names[0].startswith("Предварительный_отчёт_день_1_")
    assert (names[0][-5:], names[1][-4:]) == (".xlsx", ".pdf")
    excel = next(m for m in aigul.bot_messages if m.document_name == names[0])
    assert excel.document_data is not None
    sheet = load_workbook(BytesIO(excel.document_data))["Отчёт"]
    assert sheet["A3"].value == "Сформировал: Айгуль"
    assert (await days.ensure_open_day(session)).id == 1  # nothing is closed


async def test_scenario_8_closing_of_day_1(
    harness: Harness,
    owner_client: UserClient,
    session: AsyncSession,
    owner_user: User,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "group_chat_id", GROUP)
    await acceptance_day_1(session, owner_user)
    await start_closing(owner_client)
    assert owner_client.last.text == "Закрытие дня №1\n\nСколько сомов за 1 USD?"
    await enter_rates(owner_client, "87,65", "0,991")

    assert owner_client.last.text == "\n".join(["День №1 — проверка перед закрытием", *DAY_1_CHECK])
    assert owner_client.last.buttons == [
        ["Закрыть день №1"],
        [texts.BTN_CHANGE_RATES],
        [texts.BTN_DONT_CLOSE],
    ]
    mark = owner_client.mark()
    await owner_client.click("Закрыть день №1")

    sent = owner_client.since(mark)
    assert sent[0].text == "День №1 закрыт. Излишки: +1 053,50 сома. Начат день №2."
    on = await closed_on(session, 1)
    assert documents(sent) == [f"Отчёт_дня_1_{on:%Y-%m-%d}.xlsx", f"Отчёт_дня_1_{on:%Y-%m-%d}.pdf"]
    assert sent[-1].text == texts.main_menu(2)
    # The other owner gets the message and both files too (TZ 13.11); the group only the text.
    second = harness.chat(SECOND_OWNER_TG_ID)
    assert second[0].text.startswith("День №1 закрыт. Излишки: +1 053,50 сома. Начат день №2.")
    assert "Закрыл: Владелец" in second[0].text
    assert len(documents(second)) == 2
    posts = harness.chat(GROUP)
    assert [post.text.splitlines()[0] for post in posts] == [
        "День №1 закрыт. Излишки: +1 053,50 сома. Начат день №2."
    ]
    assert documents(posts) == []
    day = await session.get(BusinessDay, 1, populate_existing=True)
    assert day is not None
    assert (day.status, day.surplus) == (DayStatus.CLOSED, D("1053.50"))


async def test_scenario_11_closing_of_day_2_and_the_archive(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    people = await acceptance_day_1(session, owner_user)
    await days.close_day(session, owner_user, 1, DAY_1_RATES)
    await acceptance_day_2(session, owner_user, people["Азамат"])

    await start_closing(owner_client)
    assert owner_client.last.buttons[0] == ["Как в прошлый раз: 87,65"]
    await enter_rates(owner_client, "87,70", "0,99")
    assert owner_client.last.text.splitlines()[-4:] == [
        "Итог: 1 878 315",
        "Начальная точка: 1 877 000",
        "Излишки: +1 315",
        "Изменение за день: +261,50",
    ]
    await owner_client.click("Закрыть день №2")
    assert "День №2 закрыт. Излишки: +1 315 сомов. Начат день №3." in [
        m.text for m in owner_client.bot_messages
    ]

    await owner_client.click(texts.BTN_REPORTS)
    await owner_client.click(texts.BTN_ARCHIVE)
    day_1, day_2 = await closed_on(session, 1), await closed_on(session, 2)
    assert owner_client.last.buttons[:2] == [
        [f"День №2 · {day_2:%d.%m.%Y} · +1 315"],
        [f"День №1 · {day_1:%d.%m.%Y} · +1 053,50"],
    ]
    await owner_client.click(owner_client.last.buttons[1][0])
    assert "Излишки: +1 053,50" in owner_client.last.text  # the snapshot of day 1
    assert owner_client.last.text.endswith(texts.CHOOSE_FORMAT)
    await owner_client.click(texts.BTN_EXCEL)
    assert documents(owner_client.bot_messages)[-1] == f"Отчёт_дня_1_{day_1:%Y-%m-%d}.xlsx"
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == "Архив закрытых дней"


async def test_previous_rate_button(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    people = await acceptance_day_1(session, owner_user)
    await days.close_day(session, owner_user, 1, DAY_1_RATES)
    await acceptance_day_2(session, owner_user, people["Азамат"])
    await start_closing(owner_client)

    await owner_client.click("Как в прошлый раз: 87,65")
    await owner_client.click("Как в прошлый раз: 0,991")

    assert owner_client.last.text.startswith("День №2 — проверка перед закрытием")
    assert "× 87,65 =" in owner_client.last.text


async def test_negative_surplus_is_warned(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_balance(session, owner_user, "100", USD)
    await adjust(session, owner_user, "-50", USD, "недостача")
    await start_closing(owner_client)

    await enter_rates(owner_client, "90")

    assert owner_client.last.text.endswith(
        "Излишки: −4 500\nИзменение за день: −4 500\n\n"
        "Внимание: излишки отрицательные. Проверьте записи и курсы."
    )
    assert owner_client.last.buttons[0] == ["Закрыть день №1"]  # closing is still allowed


async def test_back_change_rates_and_dont_close(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await acceptance_day_1(session, owner_user)
    await start_closing(owner_client)
    await owner_client.send("абв")
    assert texts.RATE_ERRORS[texts.NumberProblem.FORMAT] in owner_client.last.text
    await enter_rates(owner_client, "87,65", "0,991")

    await owner_client.click(texts.BTN_CHANGE_RATES)
    assert owner_client.last.text == "Закрытие дня №1\n\nСколько сомов за 1 USD?"
    await enter_rates(owner_client, "88", "1")
    assert "× 88 = 792 000" in owner_client.last.text
    await owner_client.click(texts.BTN_DONT_CLOSE)
    assert owner_client.last.text == texts.main_menu(1)

    await start_closing(owner_client)
    await enter_rates(owner_client, "87,65")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == "Закрытие дня №1\n\nСколько сомов за 1 USD?"
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == texts.main_menu(1)
    assert (await days.ensure_open_day(session)).id == 1

    await start_preliminary(owner_client)
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == "Отчёты"


async def test_day_closed_by_the_other_owner_meanwhile(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_balance(session, owner_user, "100", USD)
    await start_closing(owner_client)
    await enter_rates(owner_client, "90")
    await days.close_day(session, owner_user, 1, {USD: D("90")})

    await owner_client.click("Закрыть день №1")

    result, menu = owner_client.bot_messages[-2:]
    assert (result.text, menu.text) == ("День №1 уже закрыт.", texts.main_menu(2))


async def test_records_in_a_new_currency_while_the_rates_are_typed(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_balance(session, owner_user, "1000000", KGS)
    await open_balance(session, owner_user, "100", USD)
    await start_closing(owner_client)
    await swap(session, owner_user, "1000", RUB, "990", KGS, rate="0.99")

    await enter_rates(owner_client, "90")

    assert owner_client.last.text == "\n\n".join(
        [
            "Закрытие дня №1\nКурсы: USD 90",
            texts.NEW_RATES_NEEDED,
            "Сколько сомов за 1 RUB?",
        ]
    )
    await enter_rates(owner_client, "0,99")
    assert owner_client.last.text.startswith("День №1 — проверка перед закрытием")


async def test_nothing_in_foreign_currencies_needs_no_rates(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await open_balance(session, owner_user, "1000", KGS)

    await start_closing(owner_client)

    assert owner_client.last.text.startswith("День №1 — проверка перед закрытием\nНаличка: 1 000")
    assert owner_client.last.buttons == [["Закрыть день №1"], [texts.BTN_DONT_CLOSE]]


async def test_helper_cannot_close_the_day(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await users.add_helper(session, owner_user, "aigul_k")
    aigul = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await aigul.send("/start")

    answer = await aigul.press(MenuCb(action=MenuAction.CLOSE_DAY).pack(), aigul.last)

    assert answer.text == texts.PERMISSION_DENIED
    assert (await days.ensure_open_day(session)).id == 1


async def test_empty_archive(owner_client: UserClient) -> None:
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_REPORTS)

    await owner_client.click(texts.BTN_ARCHIVE)

    assert owner_client.last.text == f"Архив закрытых дней\n{texts.ARCHIVE_EMPTY}"
