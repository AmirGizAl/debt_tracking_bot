"""«Балансы» (TZ 13.7): the five balances of the open day."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import BalancesAction, BalancesCb, MenuAction, MenuCb
from app.bot.keyboards import balances as kb
from app.bot.ui import answer, leave_any, show_screen
from app.db.models import User
from app.services import days, ledger

router = Router(name="balances")


async def show_balances(
    event: Message | CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    await leave_any(event, state, bot)
    day_number = await days.open_day_number(session)
    text = texts.balances_screen(day_number, await ledger.balances(session))
    await show_screen(event, bot, text, kb.screen(user))


@router.callback_query(MenuCb.filter(F.action == MenuAction.BALANCES))
@router.callback_query(BalancesCb.filter(F.action == BalancesAction.SHOW))
async def open_balances(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await show_balances(callback, state, bot, session, user)
    await answer(callback)


@router.callback_query(
    BalancesCb.filter(F.action.in_({BalancesAction.RECORDS, BalancesAction.ADJUST}))
)
async def coming_soon(callback: CallbackQuery) -> None:
    # «Записи дня» and «Корректировка» come with the record card (docs/V2_PLAN.md, stage 6).
    await answer(callback, texts.SECTION_SOON)
