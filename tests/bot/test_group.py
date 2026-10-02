"""Notifications to the group of GROUP_CHAT_ID (customer's request, kept for version 2).

Posts about records come with the record scenarios of version 2 (docs/V2_PLAN.md, stage 6);
helper events and the discovery of the group id work already.
"""

import logging

import pytest
from aiogram import Bot
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.dispatcher import check_group
from app.config import Settings
from app.db.models import User
from app.services import users
from tests.bot.harness import BOT_TOKEN, FakeTelegram, Harness, UserClient
from tests.conftest import OWNER_TG_ID, SECOND_OWNER_TG_ID

GROUP = -1001234567890


@pytest.fixture
def group(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> int:
    """GROUP_CHAT_ID for one test: the dispatcher and its settings live for the whole session."""
    monkeypatch.setattr(settings, "group_chat_id", GROUP)
    return GROUP


async def join_helper(harness: Harness, owner_user: User, session: AsyncSession) -> UserClient:
    await users.add_helper(session, owner_user, "aigul_k")
    helper = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await helper.send("/start")
    return helper


async def test_helper_events_are_posted(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User, group: int
) -> None:
    await join_helper(harness, owner_user, session)

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_SETTINGS)
    await owner_client.click(texts.BTN_HELPERS)
    await owner_client.click("Айгуль (@aigul_k) · активен")
    await owner_client.click(texts.BTN_DELETE)
    await owner_client.click(texts.BTN_CONFIRM_DELETE)

    assert [post.text for post in harness.chat(group)] == [
        "Новый помощник в боте: Айгуль (@aigul_k).",
        "Помощник @aigul_k удалён.",
    ]
    assert all(post.markup is None for post in harness.chat(group))


async def test_every_owner_hears_about_a_new_helper(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await join_helper(harness, owner_user, session)

    notice = "Новый помощник в боте: Айгуль (@aigul_k)."
    assert [m.text for m in harness.chat(OWNER_TG_ID)] == [notice]
    assert [m.text for m in harness.chat(SECOND_OWNER_TG_ID)] == [notice]


async def test_nothing_is_posted_without_group_chat_id(
    harness: Harness, session: AsyncSession, owner_user: User
) -> None:
    await join_helper(harness, owner_user, session)

    assert [chat for chat in harness.telegram.history if chat < 0] == []


async def test_unreachable_group_does_not_break_anything(
    harness: Harness,
    session: AsyncSession,
    owner_user: User,
    group: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness.telegram.unreachable_chats.add(group)  # e.g. the bot was removed from the group

    with caplog.at_level(logging.WARNING):
        helper = await join_helper(harness, owner_user, session)

    assert helper.last.text == texts.main_menu(1)
    assert f"Cannot post to the group {group}" in caplog.text


async def test_group_that_became_a_supergroup_still_gets_posts(
    harness: Harness,
    session: AsyncSession,
    owner_user: User,
    group: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    supergroup = -1009876543210
    harness.telegram.migrated_chats[group] = supergroup

    with caplog.at_level(logging.WARNING):
        await join_helper(harness, owner_user, session)

    assert harness.chat(supergroup)[0].text == "Новый помощник в боте: Айгуль (@aigul_k)."
    assert f"set GROUP_CHAT_ID={supergroup} in .env" in caplog.text


async def test_second_owner_learns_the_id_too(
    harness: Harness, second_owner_client: UserClient
) -> None:
    await harness.add_bot_to_chat(second_owner_client, -100556, "Касса")

    assert "GROUP_CHAT_ID=-100556" in second_owner_client.last.text


# --- finding out the id of a group -------------------------------------------------------------


async def test_owner_learns_the_id_of_a_new_group(
    harness: Harness, owner_client: UserClient
) -> None:
    await harness.add_bot_to_chat(owner_client, -100555, "Учёт <команда>")

    assert owner_client.last.html == texts.bot_added_to_group("Учёт <команда>", -100555, False)
    assert owner_client.last.text == (
        "Бот добавлен в группу «Учёт <команда>». Чтобы он публиковал туда уведомления о записях, "
        "укажите в файле .env строку\nGROUP_CHAT_ID=-100555\nи перезапустите бота."
    )
    assert harness.chat(-100555) == []  # the bot says nothing in the group itself


async def test_owner_adds_the_configured_group(
    harness: Harness, owner_client: UserClient, group: int
) -> None:
    await harness.add_bot_to_chat(owner_client, group, "Учёт")

    assert owner_client.last.text == (
        "Бот добавлен в группу «Учёт». Уведомления о записях будут приходить туда."
    )


async def test_group_added_by_someone_else_is_only_logged(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    stranger = harness.user(5555, username="stranger")

    with caplog.at_level(logging.INFO):
        await harness.add_bot_to_chat(stranger, -100777, "Чужая группа")

    assert harness.chat(OWNER_TG_ID) == []
    assert "chat_id=-100777" in caplog.text


async def test_unblocking_the_bot_in_private_is_not_a_group(
    harness: Harness, owner_client: UserClient
) -> None:
    await harness.add_bot_to_chat(owner_client, OWNER_TG_ID, None, chat_type="private")

    assert harness.chat(OWNER_TG_ID) == []


# --- configuration -----------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "expected"), [("", None), ("-1001234567890", -1001234567890)])
def test_group_chat_id_setting(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int | None
) -> None:
    monkeypatch.setenv("GROUP_CHAT_ID", value)

    settings = Settings(
        _env_file=None, bot_token=BOT_TOKEN, owner_telegram_ids="1", database_url="postgresql://x"
    )

    assert settings.group_chat_id == expected


def test_group_chat_id_must_be_a_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUP_CHAT_ID", str(OWNER_TG_ID))  # a person's id pasted by mistake

    with pytest.raises(ValidationError, match="GROUP_CHAT_ID must be the negative id"):
        Settings(
            _env_file=None,
            bot_token=BOT_TOKEN,
            owner_telegram_ids="1",
            database_url="postgresql://x",
        )


async def test_startup_check_of_the_group(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    telegram = FakeTelegram()
    telegram.groups[GROUP] = "Учёт"
    bot = Bot(BOT_TOKEN, session=telegram)

    with caplog.at_level(logging.INFO):
        await check_group(bot, settings)
        await check_group(bot, settings.model_copy(update={"group_chat_id": GROUP}))
        await check_group(bot, settings.model_copy(update={"group_chat_id": -100404}))

    assert "GROUP_CHAT_ID is not set" in caplog.text
    assert f"posted to the group 'Учёт' (chat_id={GROUP})" in caplog.text
    assert "Cannot reach the group GROUP_CHAT_ID=-100404" in caplog.text
