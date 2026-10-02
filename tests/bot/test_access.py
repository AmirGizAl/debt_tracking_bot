import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb
from app.db.models import User, UserStatus
from app.services import users
from tests.bot.harness import FakeMessage, Harness, UserClient
from tests.conftest import OWNER_TG_ID, create_user

MENU = texts.main_menu(1)
MAIN_MENU_BUTTONS = [
    [texts.BTN_EXCHANGE],
    [texts.BTN_TO_PAY, texts.BTN_TO_RECEIVE],
    [texts.BTN_LOANS, texts.BTN_CLIENTS],
    [texts.BTN_BALANCES, texts.BTN_REPORTS],
]
OWNER_ROW = [texts.BTN_CLOSE_DAY, texts.BTN_SETTINGS]


async def test_owner_sees_main_menu_on_start(owner_client: UserClient) -> None:
    await owner_client.send("/start")

    assert owner_client.last.text == "День №1. Выберите действие:"
    assert owner_client.last.buttons == [*MAIN_MENU_BUTTONS, OWNER_ROW]


async def test_every_listed_owner_has_the_same_menu(second_owner_client: UserClient) -> None:
    await second_owner_client.send("/start")

    assert second_owner_client.last.buttons == [*MAIN_MENU_BUTTONS, OWNER_ROW]


async def test_helper_menu_has_no_owner_row(harness: Harness, session: AsyncSession) -> None:
    await create_user(session, telegram_id=2002, username="aigul_k", full_name="Айгуль")
    helper = harness.user(2002, username="aigul_k")

    await helper.send("/menu")

    assert helper.last.text == MENU
    assert helper.last.buttons == MAIN_MENU_BUTTONS


async def test_menu_shows_the_open_day(
    owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await session.execute(
        text(
            "UPDATE business_days SET status = 'closed', closed_at = now(), closed_by_id = :owner,"
            " rates = '{}', report = '{}', surplus = 0"
        ),
        {"owner": owner_user.id},
    )
    await session.commit()

    await owner_client.send("/menu")

    assert owner_client.last.text == "День №2. Выберите действие:"


@pytest.mark.parametrize(
    "action",
    [
        MenuAction.EXCHANGE,
        MenuAction.TO_PAY,
        MenuAction.TO_RECEIVE,
        MenuAction.LOANS,
        MenuAction.BALANCES,
        MenuAction.REPORTS,
        MenuAction.CLOSE_DAY,
    ],
)
async def test_sections_of_later_stages_say_so(
    owner_client: UserClient, action: MenuAction
) -> None:
    await owner_client.send("/menu")

    answer = await owner_client.press(MenuCb(action=action).pack(), owner_client.last)

    assert answer.text == texts.SECTION_SOON


@pytest.mark.parametrize("data", ["m:cash", "m:lend", "r:op:3", "o:save:", "rp:k:summary"])
async def test_buttons_of_version_1_are_stale(owner_client: UserClient, data: str) -> None:
    # A v1 "Открыть запись №3" must not open the unrelated record №3 of version 2.
    await owner_client.send("/menu")

    answer = await owner_client.press(data, owner_client.last)

    assert answer.text == texts.STALE_ACTION


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

    answer = await stranger.press(MenuCb(action=MenuAction.BALANCES).pack(), fake_menu)

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
    assert owner_client.last.text == MENU

    mark = owner_client.mark()
    await owner_client.send("/cancel")
    # Nothing to cancel: just the menu again.
    assert [m.text for m in owner_client.since(mark)] == [MENU]


async def test_random_text_outside_scenario_shows_menu(owner_client: UserClient) -> None:
    await owner_client.send("привет")

    assert owner_client.last.text == MENU


async def test_unknown_button_is_stale(owner_client: UserClient) -> None:
    await owner_client.send("/start")

    answer = await owner_client.press("zz:unknown", owner_client.last)

    assert answer.text == texts.STALE_ACTION


async def test_home_button_edits_message_into_menu(owner_client: UserClient) -> None:
    await owner_client.send("/start")
    menu = owner_client.last

    await owner_client.press(MenuCb(action=MenuAction.HOME).pack(), menu)

    assert owner_client.last is menu
    assert menu.text == MENU


async def test_unexpected_error_is_reported(
    owner_client: UserClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(users, "update_full_name", broken)

    await owner_client.send("/start")

    assert owner_client.last.text == texts.UNEXPECTED_ERROR
