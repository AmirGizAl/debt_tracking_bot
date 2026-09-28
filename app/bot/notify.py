"""Messages the bot sends on its own: to the owner and to the group of GROUP_CHAT_ID.

All of them are best effort. A failed notification must never undo or hide the action that
caused it, so they go out after the user has got the result and never raise.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramMigrateToChat
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.config import Settings
from app.services import balances, cash, operations

logger = logging.getLogger(__name__)


async def notify_owner(
    bot: Bot, settings: Settings, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """The owner may not have opened the bot yet or may have blocked it."""
    try:
        await bot.send_message(settings.owner_telegram_id, text, reply_markup=reply_markup)
    except TelegramAPIError as exc:
        logger.warning("Cannot notify the owner: %s", exc)


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


async def post_record(
    bot: Bot, settings: Settings, session: AsyncSession, operation_id: int
) -> None:
    """A new record or a reversal, with the client's balance and the cash after it."""
    if settings.group_chat_id is None:
        return
    try:
        operation = await operations.get_operation(session, operation_id)
        balance = await balances.client_balance(
            session, operation.client_id, operation.debt_currency
        )
        cash_after = await cash.cash_balance(session, operation.cash_currency)
    except Exception:
        logger.exception("Cannot prepare the group post about record %s", operation_id)
        return
    text = texts.group_record_notice(operation, balance, cash_after, settings.zone)
    await notify_group(bot, settings, text)


async def post_adjustment(
    bot: Bot, settings: Settings, session: AsyncSession, adjustment_id: int
) -> None:
    """A cash adjustment with the cash after it."""
    if settings.group_chat_id is None:
        return
    try:
        adjustment = await cash.get_adjustment(session, adjustment_id)
        assert adjustment is not None
        cash_after = await cash.cash_balance(session, adjustment.currency)
    except Exception:
        logger.exception("Cannot prepare the group post about adjustment %s", adjustment_id)
        return
    text = texts.group_adjustment_notice(adjustment, cash_after, settings.zone)
    await notify_group(bot, settings, text)
