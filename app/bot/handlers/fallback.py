"""Catch-all handlers. This router must be included last."""

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from app.bot import texts
from app.bot.keyboards.common import main_menu
from app.bot.ui import answer
from app.db.models import User

router = Router(name="fallback")


@router.callback_query()
async def stale_callback(callback: CallbackQuery) -> None:
    # A button of an old message or of an abandoned scenario (TZ 11).
    await answer(callback, texts.STALE_ACTION)


@router.message(StateFilter(None))
async def outside_scenario(message: Message, user: User) -> None:
    # Keep the menu one message away whatever the user types.
    await message.answer(texts.MAIN_MENU, reply_markup=main_menu(user))


@router.message()
async def unexpected_input(message: Message) -> None:
    await message.answer(texts.UNEXPECTED_INPUT)
