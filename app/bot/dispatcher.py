import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, BotCommandScopeDefault
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot import texts
from app.bot.handlers import (
    cash,
    clients,
    errors,
    fallback,
    group,
    lend_borrow,
    menu,
    operation_card,
    operation_steps,
    panel,
    repay,
    reports,
    start,
)
from app.bot.handlers import settings as settings_handlers
from app.bot.middlewares.access import AccessMiddleware
from app.bot.middlewares.db import DbSessionMiddleware
from app.config import Settings

logger = logging.getLogger(__name__)

BOT_COMMANDS = (
    ("start", texts.CMD_START),
    ("menu", texts.CMD_MENU),
    ("cancel", texts.CMD_CANCEL),
)


def create_storage(settings: Settings) -> BaseStorage:
    if settings.redis_url:
        return RedisStorage.from_url(settings.redis_url)
    logger.warning("REDIS_URL is not set: dialog states are kept in memory and lost on restart")
    return MemoryStorage()


def create_bot(settings: Settings) -> Bot:
    session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
    return Bot(
        token=settings.bot_token.get_secret_value(),
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def create_dispatcher(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: BaseStorage | None = None,
) -> Dispatcher:
    # SimpleEventIsolation processes updates of one user strictly one by one: a double tap on
    # "Сохранить" (or a re-delivered callback) sees the finished first attempt, not a race.
    dispatcher = Dispatcher(
        storage=storage or MemoryStorage(),
        events_isolation=SimpleEventIsolation(),
    )
    dispatcher["settings"] = settings

    dispatcher.update.outer_middleware(DbSessionMiddleware(sessionmaker))
    access = AccessMiddleware(settings)
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)

    dispatcher.include_routers(
        errors.router,
        group.router,  # only the bot's own membership in groups, never messages there
        # Commands first: /menu and /cancel must win over any step that waits for text.
        start.router,
        menu.router,
        # The section panel sends plain texts: they must win over steps that wait for text.
        panel.router,
        settings_handlers.router,
        clients.router,
        lend_borrow.router,
        repay.router,
        operation_steps.router,
        operation_card.router,
        cash.router,
        reports.router,
        fallback.router,
    )
    return dispatcher


async def set_commands(bot: Bot) -> None:
    # Only the default scope: per-chat scopes fail with "chat not found" for users who never
    # opened the bot, and one such failure used to crash the startup of an earlier bot.
    commands = [BotCommand(command=name, description=text) for name, text in BOT_COMMANDS]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except TelegramAPIError as exc:
        logger.warning("Cannot register bot commands, will retry on next start: %s", exc)


async def check_group(bot: Bot, settings: Settings) -> None:
    """Log where group notifications go, or why they cannot (e.g. the bot is not in the group)."""
    if settings.group_chat_id is None:
        logger.info("GROUP_CHAT_ID is not set: nothing is posted to a group")
        return
    try:
        chat = await bot.get_chat(settings.group_chat_id)
    except TelegramAPIError as exc:
        logger.warning(
            "Cannot reach the group GROUP_CHAT_ID=%s, is the bot a member there? %s",
            settings.group_chat_id,
            exc,
        )
        return
    logger.info("New records are posted to the group %r (chat_id=%s)", chat.title, chat.id)


async def prepare_bot(bot: Bot, attempts: int = 12, delay: float = 5.0) -> None:
    """Make sure polling can start: Telegram may be unreachable for a while after boot."""
    for attempt in range(1, attempts + 1):
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            break
        except TelegramNetworkError as exc:
            if attempt == attempts:
                raise
            logger.warning("Telegram is unreachable (%s/%s): %s", attempt, attempts, exc)
            await asyncio.sleep(delay)
    await set_commands(bot)
