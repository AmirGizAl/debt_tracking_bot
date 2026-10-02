from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards.common import main_menu, panel
from app.bot.ui import menu_text, reset_scenario
from app.db.models import User
from app.services import users

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if message.from_user is not None:
        await users.update_full_name(session, user, message.from_user.full_name)
    await reset_scenario(state, bot, message.chat.id)
    # The panel stays under the input field from now on; /start brings it back if it is gone.
    await message.answer(texts.PANEL_GREETING, reply_markup=panel(user))
    await message.answer(await menu_text(session), reply_markup=main_menu(user))
