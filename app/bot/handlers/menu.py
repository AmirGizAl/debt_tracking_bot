from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb, NoopCb
from app.bot.keyboards.common import main_menu
from app.bot.ui import (
    answer,
    drop_keyboard,
    edit_or_send,
    menu_text,
    reset_scenario,
    screen_id,
    send_menu,
)
from app.db.models import User

router = Router(name="menu")


@router.message(Command("menu"))
async def cmd_menu(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await reset_scenario(state, bot, message.chat.id)
    await send_menu(bot, message.chat.id, user, session)


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if await reset_scenario(state, bot, message.chat.id):
        await message.answer(texts.ACTION_CANCELLED)
    await send_menu(bot, message.chat.id, user, session)


@router.callback_query(MenuCb.filter(F.action == MenuAction.HOME))
async def to_home(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if callback.message is None:
        await answer(callback, texts.STALE_ACTION)
        return
    current_screen = await screen_id(state)
    if current_screen != callback.message.message_id:
        await drop_keyboard(bot, callback.message.chat.id, current_screen)
    await state.clear()
    await edit_or_send(bot, callback.message, await menu_text(session), main_menu(user))
    await answer(callback)


@router.callback_query(NoopCb.filter())
async def noop(callback: CallbackQuery) -> None:
    await answer(callback)
