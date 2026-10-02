"""Messages the bot sends on its own: to the owners and to the group of GROUP_CHAT_ID.

All of them are best effort. A failed notification must never undo or hide the action that
caused it, so they go out after the user has got the result and never raise.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramMigrateToChat
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import changes, texts
from app.config import Settings
from app.domain.entries import LOAN_TYPES
from app.services import ledger, users

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


async def post_record(bot: Bot, settings: Settings, session: AsyncSession, record_id: int) -> None:
    """A new record or a cancellation, with the balances and obligations it changed."""
    if settings.group_chat_id is None:
        return
    try:
        operation = await ledger.get_operation(session, record_id)
        client_name = operation.client.name if operation.client is not None else None
        after = await changes.state_lines(
            session,
            operation.entries,
            operation.client_id,
            client_name,
            pending=False,
            obligations_first=operation.type in LOAN_TYPES,
        )
    except Exception:
        logger.exception("Cannot prepare the group post about record %s", record_id)
        return
    await notify_group(bot, settings, texts.group_record_notice(operation, after, settings.zone))
