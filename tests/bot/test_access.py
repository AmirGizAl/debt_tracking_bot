import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb
from app.db.models import User, UserStatus
from app.services import users
from tests.bot.harness import FakeMessage, Harness, UserClient
from tests.conftest import OWNER_TG_ID, create_user

MAIN_MENU_BUTTONS = [
    [texts.BTN_LEND, texts.BTN_REPAY_IN],
    [texts.BTN_BORROW, texts.BTN_REPAY_OUT],
    [texts.BTN_CLIENTS, texts.BTN_CASH],
]


async def test_owner_sees_main_menu_on_start(owner_client: UserClient) -> None:
    await owner_client.send("/start")

    assert owner_client.last.text == texts.MAIN_MENU
    assert owner_client.last.buttons == [
        *MAIN_MENU_BUTTONS,
        [texts.BTN_REPORTS, texts.BTN_SETTINGS],
    ]


async def test_start_stores_owner_full_name(
    owner_client: UserClient, session: AsyncSession
) -> None:
    await owner_client.send("/start")

    owner = await session.scalar(select(User).where(User.telegram_id == OWNER_TG_ID))
    assert owner is not None
    assert owner.full_name == "Владелец"


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        ("stranger", texts.NO_ACCESS),
        (None, f"{texts.NO_ACCESS}\n{texts.NO_ACCESS_NO_USERNAME}"),
    ],
)
async def test_stranger_is_denied(harness: Harness, username: str | None, expected: str) -> None:
    stranger = harness.user(5555, username=username)

    await stranger.send("/start")

    assert [m.text for m in stranger.bot_messages] == [expected]


async def test_stranger_button_press_is_denied(harness: Harness) -> None:
    stranger = harness.user(5555, username="stranger")
    fake_menu = FakeMessage(chat_id=5555, message_id=1, from_bot=True, html="x")

    answer = await stranger.press(MenuCb(action=MenuAction.CASH).pack(), fake_menu)

    assert answer.text == texts.NO_ACCESS
    assert answer.show_alert
    assert stranger.bot_messages == []


async def test_deleted_helper_is_denied(harness: Harness, session: AsyncSession) -> None:
    await create_user(session, telegram_id=7777, username="gone_user", status=UserStatus.DELETED)
    gone = harness.user(7777, username="gone_user")

    await gone.send("/menu")

    assert gone.last.text == texts.NO_ACCESS


async def test_album_is_answered_once(harness: Harness) -> None:
    stranger = harness.user(5555, username="stranger")

    for _ in range(3):
        await stranger.send(None, media_group_id="album-1", caption="фото")

    assert len(stranger.bot_messages) == 1


async def test_group_chats_are_ignored(owner_client: UserClient) -> None:
    await owner_client.send("/start", chat_type="group")

    assert owner_client.bot_messages == []


async def test_menu_and_cancel_commands(owner_client: UserClient) -> None:
    await owner_client.send("/menu")
    assert owner_client.last.text == texts.MAIN_MENU

    mark = owner_client.mark()
    await owner_client.send("/cancel")
    # Nothing to cancel: just the menu again.
    assert [m.text for m in owner_client.since(mark)] == [texts.MAIN_MENU]


async def test_random_text_outside_scenario_shows_menu(owner_client: UserClient) -> None:
    await owner_client.send("привет")

    assert owner_client.last.text == texts.MAIN_MENU


async def test_unknown_button_is_stale(owner_client: UserClient) -> None:
    await owner_client.send("/start")

    answer = await owner_client.press("zz:unknown", owner_client.last)

    assert answer.text == texts.STALE_ACTION


async def test_home_button_edits_message_into_menu(owner_client: UserClient) -> None:
    await owner_client.send("/start")
    menu = owner_client.last

    await owner_client.press(MenuCb(action=MenuAction.HOME).pack(), menu)

    assert owner_client.last is menu
    assert menu.text == texts.MAIN_MENU


async def test_unexpected_error_is_reported(
    owner_client: UserClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(users, "update_full_name", broken)

    await owner_client.send("/start")

    assert owner_client.last.text == texts.UNEXPECTED_ERROR
