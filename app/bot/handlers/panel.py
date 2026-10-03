"""The section panel under the input field (reply keyboard, always shown).

A tap sends the button text; it opens the section like the main-menu button and abandons any
scenario. This router comes right after the commands, before any step that waits for text.
"""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.flows import exchange
from app.bot.handlers import day_report
from app.bot.handlers.balances import show_balances
from app.bot.handlers.clients import show_clients
from app.bot.handlers.loans import show_loans
from app.bot.handlers.reports import show_reports
from app.bot.handlers.settings import show_settings
from app.bot.handlers.settlements import show_waiting
from app.bot.keyboards.common import MENU_ROWS, OWNER_ROW
from app.config import Settings
from app.db.models import User

router = Router(name="panel")

PANEL_TEXTS = frozenset(text for row in (*MENU_ROWS, OWNER_ROW) for text, _ in row)
OWNER_TEXTS = frozenset(text for text, _ in OWNER_ROW)


@router.message(F.text.in_(PANEL_TEXTS))
async def section_button(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    if message.text in OWNER_TEXTS and not user.is_owner:
        # A helper has no such buttons; typing the words opens nothing (TZ 5).
        await message.answer(texts.PERMISSION_DENIED)
        return
    if message.text == texts.BTN_EXCHANGE:
        await exchange.begin(message, state, bot)
    elif message.text in (texts.BTN_TO_PAY, texts.BTN_TO_RECEIVE):
        paying = message.text == texts.BTN_TO_PAY
        await show_waiting(message, state, bot, session, paying)
    elif message.text == texts.BTN_LOANS:
        await show_loans(message, state, bot)
    elif message.text == texts.BTN_BALANCES:
        await show_balances(message, state, bot, session, user)
    elif message.text == texts.BTN_CLIENTS:
        await show_clients(message, state, bot, session)
    elif message.text == texts.BTN_REPORTS:
        await show_reports(message, state, bot)
    elif message.text == texts.BTN_CLOSE_DAY:
        await day_report.begin(
            message, state, bot, session, user, settings, day_report.Purpose.CLOSING
        )
    elif message.text == texts.BTN_SETTINGS:
        await show_settings(message, state, bot)
