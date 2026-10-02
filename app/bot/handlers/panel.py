"""The section panel under the input field (reply keyboard, always shown).

A tap sends the button text; it opens the section like the main-menu button and abandons any
scenario. This router comes right after the commands, before any step that waits for text.
"""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.handlers.clients import show_clients
from app.bot.handlers.settings import show_settings
from app.bot.keyboards.common import MENU_ROWS, OWNER_ROW
from app.bot.ui import leave_any
from app.db.models import User

router = Router(name="panel")

PANEL_TEXTS = frozenset(text for row in (*MENU_ROWS, OWNER_ROW) for text, _ in row)
OWNER_TEXTS = frozenset(text for text, _ in OWNER_ROW)


@router.message(F.text.in_(PANEL_TEXTS))
async def section_button(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if message.text in OWNER_TEXTS and not user.is_owner:
        # A helper has no such buttons; typing the words opens nothing (TZ 5).
        await message.answer(texts.PERMISSION_DENIED)
        return
    if message.text == texts.BTN_CLIENTS:
        await show_clients(message, state, bot, session)
    elif message.text == texts.BTN_SETTINGS:
        await show_settings(message, state, bot)
    else:
        # Sections of version 2 that are not built yet (docs/V2_PLAN.md).
        await leave_any(message, state, bot)
        await message.answer(texts.SECTION_SOON)
