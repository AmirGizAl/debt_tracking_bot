"""«Выдал в долг» and «Взял в долг» (TZ 12.3): client -> currency -> amount -> comment.

The record is dated today: the date step was removed at the customer's request (28.09.2026).
"""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import MenuAction, MenuCb, OpAction, OpCb
from app.bot.flows import operation
from app.bot.states import OperationFlow
from app.bot.ui import FlowOf, OnScreen, answer
from app.domain.currency import Currency
from app.domain.operations import NEW_DEBT_TYPES, OperationType

router = Router(name="lend_borrow")

ENTRIES = {MenuAction.LEND: OperationType.LEND, MenuAction.BORROW: OperationType.BORROW}


@router.callback_query(MenuCb.filter(F.action.in_(set(ENTRIES))))
async def start(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await operation.begin(callback, state, bot, session, ENTRIES[callback_data.action])
    await answer(callback)


@router.callback_query(
    OperationFlow.currency,
    OpCb.filter(F.action == OpAction.CURRENCY),
    OnScreen(),
    FlowOf(*NEW_DEBT_TYPES),
)
async def choose_currency(
    callback: CallbackQuery,
    callback_data: OpCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    flow = await operation.load(state)
    assert flow is not None
    # A new debt is always in one currency (TZ 6.3).
    flow.debt_currency = Currency(callback_data.value)
    flow.other_currency, flow.pay_currency, flow.rate = False, None, None
    await operation.store(state, flow)
    await operation.show_amount(callback, state, bot, session, flow)
    await answer(callback)
