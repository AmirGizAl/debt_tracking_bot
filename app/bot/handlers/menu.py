from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb, NoopCb
from app.bot.keyboards.common import main_menu
from app.bot.ui import answer, drop_keyboard, edit_or_send, reset_scenario, screen_id
from app.db.models import User

router = Router(name="menu")


async def send_main_menu(bot: Bot, chat_id: int, user: User) -> None:
    await bot.send_message(chat_id, texts.MAIN_MENU, reply_markup=main_menu(user))


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, bot: Bot, user: User) -> None:
    await reset_scenario(state, bot, message.chat.id)
    await send_main_menu(bot, message.chat.id, user)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot, user: User) -> None:
    if await reset_scenario(state, bot, message.chat.id):
        await message.answer(texts.ACTION_CANCELLED)
    await send_main_menu(bot, message.chat.id, user)


@router.callback_query(MenuCb.filter(F.action == MenuAction.HOME))
async def to_home(callback: CallbackQuery, state: FSMContext, bot: Bot, user: User) -> None:
    if callback.message is None:
        await answer(callback, texts.STALE_ACTION)
        return
    current_screen = await screen_id(state)
    if current_screen != callback.message.message_id:
        await drop_keyboard(bot, callback.message.chat.id, current_screen)
    await state.clear()
    await edit_or_send(bot, callback.message, texts.MAIN_MENU, main_menu(user))
    await answer(callback)


@router.callback_query(NoopCb.filter())
async def noop(callback: CallbackQuery) -> None:
    await answer(callback)
