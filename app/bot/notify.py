"""Messages the bot sends on its own: to the owners and to the group of GROUP_CHAT_ID.

All of them are best effort. A failed notification must never undo or hide the action that
caused it, so they go out after the user has got the result and never raise.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramMigrateToChat
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services import users

logger = logging.getLogger(__name__)


async def notify_owners(
    bot: Bot,
    session: AsyncSession,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Every active owner gets it (TZ 13.11); an owner who never opened the bot is skipped."""
    for owner in await users.active_owners(session):
        assert owner.telegram_id is not None
        try:
            await bot.send_message(owner.telegram_id, text, reply_markup=reply_markup)
        except TelegramAPIError as exc:
            logger.warning("Cannot notify the owner %s: %s", owner.telegram_id, exc)


async def notify_group(bot: Bot, settings: Settings, text: str) -> None:
    """Post to the notification group; nothing happens if GROUP_CHAT_ID is not set.

    Posts carry no buttons: the bot does not answer anything in groups.
    """
    chat_id = settings.group_chat_id
    if chat_id is None:
        return
    try:
        try:
            await bot.send_message(chat_id, text)
        except TelegramMigrateToChat as exc:
            # A group turns into a supergroup with a new id, e.g. when its settings change.
            logger.warning(
                "Group %s became a supergroup: set GROUP_CHAT_ID=%s in .env",
                chat_id,
                exc.migrate_to_chat_id,
            )
            await bot.send_message(exc.migrate_to_chat_id, text)
    except TelegramAPIError as exc:
        logger.warning("Cannot post to the group %s: %s", chat_id, exc)
