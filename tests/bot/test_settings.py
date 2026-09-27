"""Helpers management through the bot UI (TZ 9, 12.9, 12.10)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import SettingsAction, SettingsCb
from app.db.models import User, UserStatus
from tests.bot.harness import Harness, UserClient
from tests.conftest import OWNER_TG_ID

HELPER_TG_ID = 2002


async def open_helpers(owner: UserClient) -> None:
    await owner.send("/start")
    await owner.click(texts.BTN_SETTINGS)
    await owner.click(texts.BTN_HELPERS)


async def invite(owner: UserClient, username: str) -> None:
    await open_helpers(owner)
    await owner.click(texts.BTN_ADD)
    assert owner.last.text == texts.ASK_HELPER_USERNAME
    await owner.send(username)


async def test_owner_invites_helper(owner_client: UserClient) -> None:
    await invite(owner_client, "@Aigul_K")

    result, menu = owner_client.bot_messages[-2:]
    assert result.text == (
        "Помощник @aigul_k добавлен. Попросите его открыть бота и нажать «Старт»."
    )
    assert menu.text == texts.MAIN_MENU


async def test_invalid_and_duplicate_usernames_keep_waiting(owner_client: UserClient) -> None:
    await invite(owner_client, "@aigul_k")
    await open_helpers(owner_client)
    await owner_client.click(texts.BTN_ADD)

    await owner_client.send("ab")
    assert owner_client.last.text == texts.INVALID_USERNAME
    await owner_client.send("AIGUL_K")
    assert owner_client.last.text == texts.USERNAME_ALREADY_ADDED
    await owner_client.send("bekzat_b")
    assert owner_client.bot_messages[-2].text.startswith("Помощник @bekzat_b добавлен.")


async def test_helper_activates_on_first_message(
    harness: Harness, owner_client: UserClient
) -> None:
    await invite(owner_client, "@aigul_k")
    helper = harness.user(HELPER_TG_ID, username="Aigul_K", first_name="Айгуль")

    await helper.send("/start")

    assert helper.last.text == texts.MAIN_MENU
    assert texts.BTN_SETTINGS not in helper.last.button_texts
    assert owner_client.last.text == "Новый помощник в боте: Айгуль (@aigul_k)."


async def test_activation_survives_unreachable_owner(
    harness: Harness, owner_client: UserClient
) -> None:
    await invite(owner_client, "@aigul_k")
    harness.telegram.unreachable_chats.add(OWNER_TG_ID)
    helper = harness.user(HELPER_TG_ID, username="aigul_k", first_name="Айгуль")

    await helper.send("hello")

    assert helper.last.text == texts.MAIN_MENU


async def test_invited_helper_without_username_gets_hint(
    harness: Harness, owner_client: UserClient
) -> None:
    await invite(owner_client, "@aigul_k")
    helper = harness.user(HELPER_TG_ID, username=None)

    await helper.send("/start")

    assert helper.last.text == f"{texts.NO_ACCESS}\n{texts.NO_ACCESS_NO_USERNAME}"


async def test_helpers_list_marks_statuses(harness: Harness, owner_client: UserClient) -> None:
    await invite(owner_client, "@aigul_k")
    await harness.user(HELPER_TG_ID, username="aigul_k", first_name="Айгуль").send("/start")
    await invite(owner_client, "@bekzat_b")

    await open_helpers(owner_client)

    assert owner_client.last.button_texts[:2] == [
        "Айгуль (@aigul_k) · активен",
        "@bekzat_b · ожидает входа",
    ]


async def test_owner_deletes_helper(
    harness: Harness, owner_client: UserClient, session: AsyncSession
) -> None:
    await invite(owner_client, "@aigul_k")
    helper = harness.user(HELPER_TG_ID, username="aigul_k", first_name="Айгуль")
    await helper.send("/start")
    await helper.click(texts.BTN_CLIENTS)  # the helper is somewhere in the menu

    await open_helpers(owner_client)
    await owner_client.click("Айгуль (@aigul_k) · активен")
    assert owner_client.last.text.splitlines()[:4] == [
        "Помощник",
        "Имя: Айгуль",
        "Никнейм: @aigul_k",
        "Статус: активен",
    ]
    await owner_client.click(texts.BTN_DELETE)
    assert owner_client.last.text == (
        "Удалить помощника @aigul_k? Доступ пропадёт сразу, его записи сохранятся."
    )
    await owner_client.click(texts.BTN_CONFIRM_DELETE)

    assert owner_client.bot_messages[-2].text == "Помощник @aigul_k удалён."
    stored = await session.scalar(select(User).where(User.username == "aigul_k"))
    assert stored is not None
    assert stored.status == UserStatus.DELETED

    await helper.send("/menu")
    assert helper.last.text == texts.NO_ACCESS


async def test_helper_cannot_open_settings(harness: Harness, owner_client: UserClient) -> None:
    await invite(owner_client, "@aigul_k")
    helper = harness.user(HELPER_TG_ID, username="aigul_k", first_name="Айгуль")
    await helper.send("/start")

    for action in (SettingsAction.HOME, SettingsAction.HELPERS, SettingsAction.ADD):
        answer = await helper.press(SettingsCb(action=action).pack(), helper.last)
        assert answer.text == texts.PERMISSION_DENIED
    assert helper.last.text == texts.MAIN_MENU
