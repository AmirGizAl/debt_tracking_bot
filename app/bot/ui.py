"""Message helpers that never break a handler after the real work is done.

Lessons from earlier bots:
- a cosmetic Telegram error ("message is not modified", "message can't be edited") raised
  after a DB write crashed the handler and confused users;
- confirmation buttons bound only to the FSM state acted on the data of a newer scenario.
  Here every scenario remembers the message that shows its current step (SCREEN_KEY), and
  scenario buttons work only on that message (`OnScreen`); the rest are stale.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    MaybeInaccessibleMessage,
    Message,
    TelegramObject,
)

from app.bot import texts
from app.bot.keyboards.common import main_menu
from app.db.models import User

logger = logging.getLogger(__name__)

SCREEN_KEY = "screen_id"


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
        sent = await bot.send_message(message.chat.id, text, reply_markup=reply_markup)
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


async def answer(callback: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    """Answer a callback query; an expired query is not worth an error message."""
    try:
        await callback.answer(text, show_alert=alert)
    except TelegramBadRequest as exc:
        logger.debug("Cannot answer callback %s: %s", callback.id, exc)


async def screen_id(state: FSMContext) -> int | None:
    value = (await state.get_data()).get(SCREEN_KEY)
    return int(value) if value is not None else None


async def reset_scenario(
    state: FSMContext, bot: Bot, chat_id: int, keep_message_id: int | None = None
) -> bool:
    """Clear FSM and strip buttons from the scenario screen unless it is `keep_message_id`.

    Returns True if a scenario was active.
    """
    active = await state.get_state() is not None
    current = await screen_id(state)
    if current != keep_message_id:
        await drop_keyboard(bot, chat_id, current)
    await state.clear()
    return active


async def show_step(
    event: Message | CallbackQuery,
    state: FSMContext,
    bot: Bot,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Show the next step of a scenario and remember which message shows it.

    After a button press the pressed message is edited; after typed text a new message is
    sent below the user's text and the previous step loses its buttons.
    """
    if isinstance(event, CallbackQuery):
        if event.message is None:
            return
        message_id = await edit_or_send(bot, event.message, text, reply_markup)
    else:
        previous = await screen_id(state)
        sent = await bot.send_message(event.chat.id, text, reply_markup=reply_markup)
        await drop_keyboard(bot, event.chat.id, previous)
        message_id = sent.message_id
    await state.update_data({SCREEN_KEY: message_id})


async def finish(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    user: User,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """End a scenario: the result goes in a new message, then the main menu (TZ 11).

    The scenario is cleared only after the result is delivered: if Telegram fails in
    between, the user can press "Сохранить" again and gets the same record back (the
    request_id makes the repeat safe).
    """
    await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await bot.send_message(chat_id, texts.MAIN_MENU, reply_markup=main_menu(user))
    await reset_scenario(state, bot, chat_id)


class OnScreen(Filter):
    """Passes callbacks only from the message that shows the current scenario step."""

    async def __call__(self, callback: CallbackQuery, state: FSMContext) -> bool:
        if callback.message is None:
            return False
        return callback.message.message_id == await screen_id(state)


async def leave_scenario(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Navigation to a plain screen abandons any scenario (its old screen loses buttons)."""
    if callback.message is None:
        await state.clear()
        return
    await reset_scenario(
        state, bot, callback.message.chat.id, keep_message_id=callback.message.message_id
    )


def chat_id_of(event: Message | CallbackQuery) -> int:
    if isinstance(event, Message):
        return event.chat.id
    return event.message.chat.id if event.message is not None else event.from_user.id


class FlowOf(Filter):
    """Passes when the active record scenario is of one of the given types."""

    def __init__(self, *op_types: str) -> None:
        self.op_types = {str(op_type) for op_type in op_types}

    async def __call__(self, event: TelegramObject, state: FSMContext) -> bool:
        return (await state.get_data()).get("op_type") in self.op_types
