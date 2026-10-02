"""The start of the bot (TZ 15.3): owners from .env, day №1, then polling."""

import logging
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import __main__ as main
from app.config import Settings
from app.db.models import BusinessDay, DayStatus, User, UserRole, UserStatus
from tests.bot.harness import BOT_TOKEN, FakeTelegram


async def test_start_syncs_owners_and_opens_day_1(
    engine: AsyncEngine,
    database_url: str,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for name, value in {
        "BOT_TOKEN": BOT_TOKEN,
        "OWNER_TELEGRAM_IDS": "1001,1003",
        "DATABASE_URL": database_url,
        "REDIS_URL": "",
        "GROUP_CHAT_ID": "",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
    telegram = FakeTelegram()
    monkeypatch.setattr(main, "create_bot", lambda settings: Bot(BOT_TOKEN, session=telegram))
    polled: list[Bot] = []

    async def fake_polling(self: Dispatcher, bot: Bot, **kwargs: Any) -> None:
        polled.append(bot)

    monkeypatch.setattr(Dispatcher, "start_polling", fake_polling)
    # Routers attach to one dispatcher only, and the bot tests already hold them.
    monkeypatch.setattr(main, "create_dispatcher", lambda *args: Dispatcher())
    monkeypatch.setattr(main, "setup_logging", lambda *args: None)

    with caplog.at_level(logging.INFO, logger="app"):
        await main.run()

    owners = await session.execute(
        select(User.telegram_id, User.role, User.status).order_by(User.id)
    )
    assert list(owners) == [
        (1001, UserRole.OWNER, UserStatus.ACTIVE),
        (1003, UserRole.OWNER, UserStatus.ACTIVE),
    ]
    day = await session.scalar(select(BusinessDay))
    assert day is not None
    assert (day.id, day.status) == (1, DayStatus.OPEN)
    assert len(polled) == 1
    assert "Bot started, owners telegram_id=1001,1003, open day №1" in caplog.text
