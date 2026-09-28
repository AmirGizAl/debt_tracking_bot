"""Notifications to the group of GROUP_CHAT_ID (customer's request of 28.09.2026)."""

import logging
import re

import pytest
from aiogram import Bot
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.dispatcher import check_group
from app.config import Settings
from app.db.models import User
from app.domain.operations import OperationType
from app.services import users
from tests.bot.harness import BOT_TOKEN, FakeMessage, FakeTelegram, Harness, UserClient
from tests.bot.records import begin, new_debt, repay_same, save
from tests.conftest import OWNER_TG_ID
from tests.factories import make_client
from tests.services.accounting import adjust, record

GROUP = -1001234567890
MADE_AT = re.compile(r" · внесено \d\d\.\d\d\.\d{4} \d\d:\d\d$")


@pytest.fixture
def group(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> int:
    """GROUP_CHAT_ID for one test: the dispatcher and its settings live for the whole session."""
    monkeypatch.setattr(settings, "group_chat_id", GROUP)
    return GROUP


def lines(post: FakeMessage) -> list[str]:
    """Lines of a group post with the time of the "Автор" line cut off."""
    return [MADE_AT.sub("", line) for line in post.text.splitlines()]


async def join_helper(harness: Harness, owner_user: User, session: AsyncSession) -> UserClient:
    await users.add_helper(session, owner_user, "aigul_k")
    helper = harness.user(2002, username="aigul_k", first_name="Айгуль")
    await helper.send("/start")
    return helper


async def cancel_last_record(client: UserClient, reason: str) -> None:
    await client.click(texts.BTN_OPEN_RECORD)
    await client.click(texts.BTN_CANCEL_RECORD)
    await client.send(reason)
    await client.click(texts.BTN_CONFIRM_CANCEL)


async def test_new_record_is_posted(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User, group: int
) -> None:
    await adjust(session, owner_user, "10000")
    await make_client(session, owner_user, "Азамат")
    await new_debt(owner_client, texts.BTN_LEND, "Азамат", "USD", "1 000", comment="на ремонт")

    assert await save(owner_client) == "Запись №1 сохранена."

    [post] = harness.chat(group)
    assert lines(post) == [
        "Новая запись №1 · Выдал в долг",
        "Клиент: Азамат",
        "Сумма: 1 000 USD",
        "Комментарий: на ремонт",
        "Автор: Владелец",
        "",
        "После записи:",
        "Азамат должен вам: 1 000 USD",
        "В кассе USD: 9 000",
    ]
    assert MADE_AT.search(post.text.splitlines()[4])
    assert post.markup is None  # nobody could press a button: the bot ignores groups


async def test_payment_in_another_currency_is_posted_with_the_rate(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User, group: int
) -> None:
    azamat = await make_client(session, owner_user, "Азамат")
    await adjust(session, owner_user, "1000")
    await record(session, owner_user, azamat, OperationType.LEND, "600")
    await begin(owner_client, texts.BTN_REPAY_IN, "Азамат")
    await owner_client.click("USD · должен 600")
    await owner_client.click(texts.BTN_OTHER_CURRENCY)
    await owner_client.click("KGS")
    await owner_client.send("52 500")
    await owner_client.send("87,5")
    await owner_client.click(texts.BTN_SKIP)

    await save(owner_client)

    assert lines(harness.chat(group)[-1]) == [
        "Новая запись №2 · Мне вернули",
        "Клиент: Азамат",
        "Получено: 52 500 KGS",
        "Курс: 1 USD = 87,5 KGS",
        "Закрывает долг: 600 USD",
        "Автор: Владелец",
        "",
        "После записи:",
        "Азамат: долга в USD нет",
        "В кассе KGS: 52 500",
    ]


async def test_repeated_save_posts_once(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User, group: int
) -> None:
    await make_client(session, owner_user, "Бекзат")
    await new_debt(owner_client, texts.BTN_BORROW, "Бекзат", "RUB", "500")
    confirmation = owner_client.last
    data = confirmation.callback_data(texts.BTN_SAVE)
    assert data is not None

    await owner_client.press(data, confirmation)
    await owner_client.press(data, confirmation)

    assert len(harness.chat(group)) == 1


async def test_helper_events_and_reversal_are_posted(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User, group: int
) -> None:
    await make_client(session, owner_user, "Азамат")
    helper = await join_helper(harness, owner_user, session)
    await new_debt(helper, texts.BTN_BORROW, "Азамат", "USD", "100")
    await save(helper)

    await cancel_last_record(helper, "ошибка в сумме")

    activation, new_record, reversal = harness.chat(group)
    assert activation.text == "Новый помощник в боте: Айгуль (@aigul_k)."
    assert lines(new_record)[:4] == [
        "Новая запись №1 · Взял в долг",
        "Клиент: Азамат",
        "Сумма: 100 USD",
        "Автор: Айгуль (@aigul_k)",
    ]
    assert lines(reversal) == [
        "Новая запись №2 · Отмена записи №1",
        "Взял в долг · Азамат · 100 USD",
        "Причина: ошибка в сумме",
        "Автор: Айгуль (@aigul_k)",
        "",
        "После отмены:",
        "Азамат: долга в USD нет",
        "В кассе USD: 0",
    ]

    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_SETTINGS)
    await owner_client.click(texts.BTN_HELPERS)
    await owner_client.click("Айгуль (@aigul_k) · активен")
    await owner_client.click(texts.BTN_DELETE)
    await owner_client.click(texts.BTN_CONFIRM_DELETE)

    assert harness.chat(group)[-1].text == "Помощник @aigul_k удалён."


async def test_owner_reversal_is_posted_too(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User, group: int
) -> None:
    await make_client(session, owner_user, "Азамат")
    await new_debt(owner_client, texts.BTN_BORROW, "Азамат", "USD", "100")
    await save(owner_client)

    await cancel_last_record(owner_client, "дубль")

    assert lines(harness.chat(group)[-1])[:3] == [
        "Новая запись №2 · Отмена записи №1",
        "Взял в долг · Азамат · 100 USD",
        "Причина: дубль",
    ]


async def test_adjustment_is_posted(
    harness: Harness, owner_client: UserClient, session: AsyncSession, group: int
) -> None:
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CASH)
    await owner_client.click(texts.BTN_ADJUST)
    await owner_client.click("USD")
    await owner_client.click(texts.BTN_ADD_MONEY)
    await owner_client.send("5 000")
    await owner_client.send("Остаток на начало работы")
    await save(owner_client)

    [post] = harness.chat(group)
    assert lines(post) == [
        "Корректировка кассы USD",
        "Изменение: +5 000 USD",
        "Причина: Остаток на начало работы",
        "Автор: Владелец",
        "",
        "После корректировки:",
        "В кассе USD: 5 000",
    ]


async def test_nothing_is_posted_without_group_chat_id(
    harness: Harness, owner_client: UserClient, session: AsyncSession, owner_user: User
) -> None:
    await make_client(session, owner_user, "Азамат")
    await repay_same(owner_client, texts.BTN_REPAY_IN, "Азамат", "USD", "100")
    await save(owner_client)
    await join_helper(harness, owner_user, session)

    assert [chat for chat in harness.telegram.history if chat < 0] == []


async def test_unreachable_group_does_not_break_saving(
    harness: Harness,
    owner_client: UserClient,
    session: AsyncSession,
    owner_user: User,
    group: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness.telegram.unreachable_chats.add(group)  # e.g. the bot was removed from the group
    await make_client(session, owner_user, "Азамат")
    await new_debt(owner_client, texts.BTN_BORROW, "Азамат", "USD", "100")

    with caplog.at_level(logging.WARNING):
        assert await save(owner_client) == "Запись №1 сохранена."

    assert owner_client.last.text == texts.MAIN_MENU
    assert f"Cannot post to the group {group}" in caplog.text


async def test_group_that_became_a_supergroup_still_gets_posts(
    harness: Harness,
    owner_client: UserClient,
    session: AsyncSession,
    owner_user: User,
    group: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    supergroup = -1009876543210
    harness.telegram.migrated_chats[group] = supergroup
    await make_client(session, owner_user, "Азамат")
    await new_debt(owner_client, texts.BTN_BORROW, "Азамат", "USD", "100")

    with caplog.at_level(logging.WARNING):
        await save(owner_client)

    assert lines(harness.chat(supergroup)[0])[0] == "Новая запись №1 · Взял в долг"
    assert f"set GROUP_CHAT_ID={supergroup} in .env" in caplog.text


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
        _env_file=None, bot_token=BOT_TOKEN, owner_telegram_id=1, database_url="postgresql://x"
    )

    assert settings.group_chat_id == expected


def test_group_chat_id_must_be_a_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROUP_CHAT_ID", str(OWNER_TG_ID))  # a person's id pasted by mistake

    with pytest.raises(ValidationError, match="GROUP_CHAT_ID must be the negative id"):
        Settings(
            _env_file=None, bot_token=BOT_TOKEN, owner_telegram_id=1, database_url="postgresql://x"
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
