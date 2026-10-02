"""Startup helpers and commands (TZ 11, 14.3)."""

from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.methods import DeleteWebhook, SetMyCommands

from app.bot import texts
from app.bot.dispatcher import create_storage, prepare_bot
from app.config import Settings
from tests.bot.harness import BOT_TOKEN, FakeTelegram, UserClient


async def test_prepare_bot_registers_commands() -> None:
    telegram = FakeTelegram()
    bot = Bot(BOT_TOKEN, session=telegram)

    await prepare_bot(bot)

    commands = [m for m in telegram.requests if isinstance(m, SetMyCommands)]
    assert [(c.command, c.description) for c in commands[0].commands] == [
        ("start", texts.CMD_START),
        ("menu", texts.CMD_MENU),
        ("cancel", texts.CMD_CANCEL),
    ]


async def test_prepare_bot_waits_for_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    # Lesson from an earlier bot: Telegram may be unreachable right after the server boots.
    telegram = FakeTelegram()
    failures = iter([True, True, False])
    original = telegram._do_DeleteWebhook

    def flaky(method: DeleteWebhook) -> Any:
        if next(failures):
            raise TelegramNetworkError(method, "timeout")
        return original(method)

    monkeypatch.setattr(telegram, "_do_DeleteWebhook", flaky)
    bot = Bot(BOT_TOKEN, session=telegram)

    await prepare_bot(bot, attempts=5, delay=0)

    assert sum(isinstance(m, DeleteWebhook) for m in telegram.requests) == 3


def test_storage_depends_on_redis_url(settings: Settings) -> None:
    assert isinstance(create_storage(settings), MemoryStorage)
    with_redis = settings.model_copy(update={"redis_url": "redis://localhost:6379/0"})
    assert isinstance(create_storage(with_redis), RedisStorage)


async def test_cancel_in_the_middle_of_a_scenario(owner_client: UserClient) -> None:
    await owner_client.send("/menu")
    await owner_client.click(texts.BTN_CLIENTS)
    await owner_client.click(texts.BTN_ADD)
    prompt = owner_client.last

    await owner_client.send("/cancel")

    assert [m.text for m in owner_client.bot_messages[-2:]] == [
        texts.ACTION_CANCELLED,
        texts.main_menu(1),
    ]
    assert prompt.markup is None  # the abandoned step lost its buttons
    await owner_client.send("Иван")  # no longer a client name
    assert owner_client.last.text == texts.main_menu(1)


async def _to_client_name(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_CLIENTS)
    await client.click(texts.BTN_ADD)


async def _to_client_comment(client: UserClient) -> None:
    await _to_client_name(client)
    await client.send("Иван")


async def _to_client_search(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_CLIENTS)
    await client.click(texts.BTN_FIND)


async def _to_helper_username(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_SETTINGS)
    await client.click(texts.BTN_HELPERS)
    await client.click(texts.BTN_ADD)


@pytest.mark.parametrize(
    "reach",
    [
        _to_client_name,
        _to_client_comment,
        _to_client_search,
        _to_helper_username,
    ],
)
@pytest.mark.parametrize("command", ["/cancel", "/menu"])
async def test_commands_win_over_text_steps(
    owner_client: UserClient, reach: Any, command: str
) -> None:
    # Regression: the command router used to come after the scenario routers, so a step
    # waiting for text took "/cancel" as a client name, an amount, a reason...
    await reach(owner_client)

    await owner_client.send(command)

    assert owner_client.bot_messages[-1].text == texts.main_menu(1)
    await owner_client.send("123")
    assert owner_client.last.text == texts.main_menu(1)  # nothing is waiting for input anymore
