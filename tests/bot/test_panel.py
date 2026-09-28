"""The section panel under the input field (reply keyboard, always shown)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Client, Operation, User
from app.services import users
from tests.bot.harness import Harness, UserClient
from tests.bot.records import save

OWNER_PANEL = [
    [texts.BTN_LEND, texts.BTN_REPAY_IN],
    [texts.BTN_BORROW, texts.BTN_REPAY_OUT],
    [texts.BTN_CLIENTS, texts.BTN_CASH],
    [texts.BTN_REPORTS, texts.BTN_SETTINGS],
]


async def test_start_installs_the_panel(owner_client: UserClient) -> None:
    await owner_client.send("/start")

    greeting, menu = owner_client.bot_messages[-2:]
    assert greeting.text == texts.PANEL_GREETING
    assert greeting.panel is not None
    assert owner_client.panel == OWNER_PANEL
    assert owner_client.panel_markup is not None
    assert owner_client.panel_markup.is_persistent
    assert owner_client.panel_markup.resize_keyboard
    # The main menu of TZ 12.1 stays as a message with its own buttons.
    assert menu.text == texts.MAIN_MENU
    assert menu.buttons == OWNER_PANEL


async def test_helper_panel_has_no_settings(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await users.add_helper(session, owner_user, "aigul_k")
    helper = harness.user(2002, username="aigul_k", first_name="Айгуль")

    await helper.send("/start")  # activation shows the panel right away

    assert helper.panel == [*OWNER_PANEL[:3], [texts.BTN_REPORTS]]
    await helper.send(texts.BTN_SETTINGS)  # typed by hand: still no settings
    assert helper.last.text == texts.PERMISSION_DENIED


@pytest.mark.parametrize(
    ("button", "first_line"),
    [
        (texts.BTN_LEND, "Кому выдаёте в долг?"),
        (texts.BTN_REPAY_IN, "Кто вернул долг?"),
        (texts.BTN_BORROW, "У кого берёте в долг?"),
        (texts.BTN_REPAY_OUT, "Кому возвращаете долг?"),
        (texts.BTN_CLIENTS, "Клиенты"),
        (texts.BTN_CASH, "Касса"),
        (texts.BTN_REPORTS, texts.REPORTS_TITLE),
        (texts.BTN_SETTINGS, "Настройки"),
    ],
)
async def test_panel_button_opens_its_section(
    owner_client: UserClient, button: str, first_line: str
) -> None:
    await owner_client.send("/start")
    menu = owner_client.last
    messages_before = len(owner_client.bot_messages)

    await owner_client.tap(button)

    assert owner_client.last.text.splitlines()[0] == first_line
    assert len(owner_client.bot_messages) == messages_before + 1  # a new message
    assert menu.text == texts.MAIN_MENU  # the old menu message is left alone


async def test_panel_interrupts_a_text_step(owner_client: UserClient) -> None:
    await owner_client.send("/start")
    await owner_client.tap(texts.BTN_BORROW)
    await owner_client.click(texts.BTN_NEW_CLIENT)
    await owner_client.send("Иван")
    await owner_client.click(texts.BTN_SKIP)
    await owner_client.click("USD")
    amount_step = owner_client.last

    await owner_client.tap(texts.BTN_CASH)

    assert owner_client.last.text.startswith("Касса\n")
    assert amount_step.markup is None  # the abandoned step lost its buttons
    await owner_client.send("100")  # not an amount any more
    assert owner_client.last.text == texts.MAIN_MENU


async def test_panel_text_is_not_taken_as_a_client_name(
    owner_client: UserClient, session: AsyncSession
) -> None:
    await owner_client.send("/start")
    await owner_client.tap(texts.BTN_CLIENTS)
    await owner_client.click(texts.BTN_ADD)

    await owner_client.tap(texts.BTN_CLIENTS)

    assert owner_client.last.text.startswith("Клиенты")
    assert await session.scalar(select(func.count()).select_from(Client)) == 0


async def test_record_started_from_the_panel_is_saved(
    owner_client: UserClient, session: AsyncSession
) -> None:
    await owner_client.send("/start")
    await owner_client.tap(texts.BTN_BORROW)
    await owner_client.click(texts.BTN_NEW_CLIENT)
    await owner_client.send("Бекзат")
    await owner_client.click(texts.BTN_SKIP)
    await owner_client.click("RUB")
    await owner_client.send("50 000")
    await owner_client.click(texts.BTN_TODAY)
    await owner_client.click(texts.BTN_SKIP)

    assert await save(owner_client) == "Запись №1 сохранена."
    assert await session.scalar(select(func.count()).select_from(Operation)) == 1


async def test_stranger_cannot_use_panel_texts(harness: Harness) -> None:
    stranger = harness.user(5555, username="stranger")

    await stranger.send(texts.BTN_CASH)

    assert stranger.last.text == texts.NO_ACCESS
    assert stranger.panel == []
