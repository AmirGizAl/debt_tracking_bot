"""The section panel under the input field (reply keyboard, always shown).

A tap sends the button text; it opens the section like the main-menu button and abandons any
scenario. This router comes right after the commands, before any step that waits for text.
"""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.flows import operation
from app.bot.handlers.cash import show_cash
from app.bot.handlers.clients import show_clients
from app.bot.handlers.reports import show_reports_menu
from app.bot.handlers.settings import show_settings
from app.db.models import User
from app.domain.operations import OperationType

router = Router(name="panel")

RECORD_BUTTONS = {
    texts.BTN_LEND: OperationType.LEND,
    texts.BTN_REPAY_IN: OperationType.REPAY_IN,
    texts.BTN_BORROW: OperationType.BORROW,
    texts.BTN_REPAY_OUT: OperationType.REPAY_OUT,
}
SECTION_BUTTONS = {texts.BTN_CLIENTS, texts.BTN_CASH, texts.BTN_REPORTS, texts.BTN_SETTINGS}


@router.message(F.text.in_(set(RECORD_BUTTONS)))
async def record_button(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    assert message.text is not None
    await operation.begin(message, state, bot, session, RECORD_BUTTONS[message.text])


@router.message(F.text.in_(SECTION_BUTTONS))
async def section_button(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if message.text == texts.BTN_CLIENTS:
        await show_clients(message, state, bot, session)
    elif message.text == texts.BTN_CASH:
        await show_cash(message, state, bot, session, user)
    elif message.text == texts.BTN_REPORTS:
        await show_reports_menu(message, state, bot)
    elif user.is_owner:
        await show_settings(message, state, bot)
    else:
        # A helper has no such button; typing the word does not open the settings (TZ 5).
        await message.answer(texts.PERMISSION_DENIED)
