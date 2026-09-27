import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from app.config import Settings

logger = logging.getLogger(__name__)


async def notify_owner(
    bot: Bot, settings: Settings, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Best effort: the owner may not have opened the bot yet or may have blocked it.

    A failed notification must never undo or hide the action that caused it.
    """
    try:
        await bot.send_message(settings.owner_telegram_id, text, reply_markup=reply_markup)
    except TelegramAPIError as exc:
        logger.warning("Cannot notify the owner: %s", exc)
