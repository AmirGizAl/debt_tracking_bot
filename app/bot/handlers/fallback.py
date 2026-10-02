"""Catch-all handlers. This router must be included last."""

from aiogram import Bot, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.ui import answer, send_menu
from app.db.models import User

router = Router(name="fallback")


@router.callback_query()
async def stale_callback(callback: CallbackQuery) -> None:
    # A button of an old message or of an abandoned scenario (TZ 13.1).
    await answer(callback, texts.STALE_ACTION)


@router.message(StateFilter(None))
async def outside_scenario(message: Message, bot: Bot, session: AsyncSession, user: User) -> None:
    # Keep the menu one message away whatever the user types.
    await send_menu(bot, message.chat.id, user, session)


@router.message()
async def unexpected_input(message: Message) -> None:
    await message.answer(texts.UNEXPECTED_INPUT)
