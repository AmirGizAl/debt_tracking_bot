"""The section panel under the input field (reply keyboard, always shown)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Client, User
from app.services import users
from tests.bot.harness import Harness, UserClient

PANEL = [
    [texts.BTN_EXCHANGE],
    [texts.BTN_TO_PAY, texts.BTN_TO_RECEIVE],
    [texts.BTN_LOANS, texts.BTN_CLIENTS],
    [texts.BTN_BALANCES, texts.BTN_REPORTS],
]
OWNER_PANEL = [*PANEL, [texts.BTN_CLOSE_DAY, texts.BTN_SETTINGS]]


async def test_start_installs_the_panel(owner_client: UserClient) -> None:
    await owner_client.send("/start")

    greeting, menu = owner_client.bot_messages[-2:]
    assert greeting.text == texts.PANEL_GREETING
    assert greeting.panel is not None
    assert owner_client.panel == OWNER_PANEL
    assert owner_client.panel_markup is not None
    assert owner_client.panel_markup.is_persistent
    assert owner_client.panel_markup.resize_keyboard
    # The main menu of TZ 13.2 stays as a message with the same buttons.
    assert menu.text == texts.main_menu(1)
    assert menu.buttons == OWNER_PANEL


async def test_helper_panel_has_no_owner_buttons(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await users.add_helper(session, owner_user, "aigul_k")
    helper = harness.user(2002, username="aigul_k", first_name="Айгуль")

    await helper.send("/start")  # activation shows the panel right away

    assert helper.panel == PANEL
    for word in (texts.BTN_SETTINGS, texts.BTN_CLOSE_DAY):
        await helper.send(word)  # typed by hand: still nothing for helpers
        assert helper.last.text == texts.PERMISSION_DENIED


@pytest.mark.parametrize(
    ("button", "first_line"),
    [
        (texts.BTN_EXCHANGE, "Обмен"),
        (texts.BTN_TO_PAY, "Ждут выдачи"),
        (texts.BTN_TO_RECEIVE, "Ждут оплаты"),
        (texts.BTN_LOANS, "Долги в сомах"),
        (texts.BTN_CLIENTS, "Клиенты"),
        (texts.BTN_BALANCES, "Балансы · день №1"),
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
    assert menu.text == texts.main_menu(1)  # the old menu message is left alone


@pytest.mark.parametrize("button", [texts.BTN_REPORTS, texts.BTN_CLOSE_DAY])
async def test_sections_of_later_stages_say_so(owner_client: UserClient, button: str) -> None:
    await owner_client.send("/start")

    await owner_client.tap(button)

    assert owner_client.last.text == texts.SECTION_SOON


async def test_panel_interrupts_a_text_step(owner_client: UserClient) -> None:
    await owner_client.send("/start")
    await owner_client.tap(texts.BTN_CLIENTS)
    await owner_client.click(texts.BTN_ADD)
    name_step = owner_client.last

    await owner_client.tap(texts.BTN_SETTINGS)

    assert owner_client.last.text.startswith("Настройки")
    assert name_step.markup is None  # the abandoned step lost its buttons
    await owner_client.send("Иван")  # not a client name any more
    assert owner_client.last.text == texts.main_menu(1)


async def test_panel_text_is_not_taken_as_a_client_name(
    owner_client: UserClient, session: AsyncSession
) -> None:
    await owner_client.send("/start")
    await owner_client.tap(texts.BTN_CLIENTS)
    await owner_client.click(texts.BTN_ADD)

    await owner_client.tap(texts.BTN_CLIENTS)

    assert owner_client.last.text.startswith("Клиенты")
    assert await session.scalar(select(func.count()).select_from(Client)) == 0


async def test_stranger_cannot_use_panel_texts(harness: Harness) -> None:
    stranger = harness.user(5555, username="stranger")

    await stranger.send(texts.BTN_BALANCES)

    assert stranger.last.text == texts.NO_ACCESS
    assert stranger.panel == []
