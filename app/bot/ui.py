"""Message helpers that never break a handler after the real work is done.

Lesson from earlier bots: a cosmetic Telegram error ("message is not modified",
"message can't be edited") raised after a DB write crashed the handler and confused users.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, MaybeInaccessibleMessage, Message

logger = logging.getLogger(__name__)

# FSM data key: id of the message that shows the current step of a scenario.
# Buttons of any other message are stale for that scenario.
SCREEN_KEY = "screen_id"


async def send(
    bot: Bot, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> Message:
    return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def edit_or_send(
    bot: Bot,
    message: MaybeInaccessibleMessage,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int:
    """Show `text` in place of `message`; send a new message if editing is impossible.

    Returns the id of the message that now shows the text.
    """
    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.message_id,
            text=text,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return message.message_id
        logger.info("Cannot edit message %s: %s; sending a new one", message.message_id, exc)
        sent = await send(bot, message.chat.id, text, reply_markup)
        return sent.message_id
    return message.message_id


async def drop_keyboard(bot: Bot, chat_id: int, message_id: int | None) -> None:
    """Remove inline buttons from an old message; failures are harmless and ignored."""
    if message_id is None:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError as exc:
        logger.debug("Cannot drop keyboard of message %s: %s", message_id, exc)


async def screen_id(state: FSMContext) -> int | None:
    value = (await state.get_data()).get(SCREEN_KEY)
    return int(value) if value is not None else None


async def reset_scenario(state: FSMContext, bot: Bot, chat_id: int) -> bool:
    """Clear FSM and strip buttons from the scenario screen. Returns True if one was active."""
    active = await state.get_state() is not None
    await drop_keyboard(bot, chat_id, await screen_id(state))
    await state.clear()
    return active


async def answer(callback: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    """Answer a callback query; an expired query is not worth an error message."""
    try:
        await callback.answer(text, show_alert=alert)
    except TelegramBadRequest as exc:
        logger.debug("Cannot answer callback %s: %s", callback.id, exc)
