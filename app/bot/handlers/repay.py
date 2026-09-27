"""«Мне вернули» and «Я вернул» (TZ 12.4).

client -> which debt -> same/other currency -> [payment currency] -> amount -> [rate]
-> date -> comment -> confirmation with warnings.
"""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb, OpAction, OpCb
from app.bot.flows import operation
from app.bot.states import OperationFlow
from app.bot.ui import FlowOf, OnScreen, answer, leave_scenario
from app.domain.currency import Currency
from app.domain.operations import REPAY_TYPES, OperationType

router = Router(name="repay")

ENTRIES = {
    MenuAction.REPAY_IN: OperationType.REPAY_IN,
    MenuAction.REPAY_OUT: OperationType.REPAY_OUT,
}


@router.callback_query(MenuCb.filter(F.action.in_(set(ENTRIES))))
async def start(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await leave_scenario(callback, state, bot)
    flow = await operation.start(state, ENTRIES[callback_data.action])
    await operation.show_client_step(callback, state, bot, session, flow)
    await answer(callback)


@router.callback_query(
    OperationFlow.currency,
    OpCb.filter(F.action == OpAction.CURRENCY),
    OnScreen(),
    FlowOf(*REPAY_TYPES),
)
async def choose_debt(
    callback: CallbackQuery, callback_data: OpCb, state: FSMContext, bot: Bot
) -> None:
    flow = await operation.load(state)
    assert flow is not None
    flow.debt_currency = Currency(callback_data.value)
    flow.other_currency, flow.pay_currency, flow.rate = False, None, None
    await operation.store(state, flow)
    await operation.show_pay_mode(callback, state, bot, flow)
    await answer(callback)


@router.callback_query(
    OperationFlow.pay_mode, OpCb.filter(F.action == OpAction.SAME_CURRENCY), OnScreen()
)
async def same_currency(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    flow = await operation.load(state)
    assert flow is not None
    flow.other_currency, flow.pay_currency, flow.rate = False, None, None
    await operation.store(state, flow)
    await operation.show_amount(callback, state, bot, session, flow)
    await answer(callback)


@router.callback_query(
    OperationFlow.pay_mode, OpCb.filter(F.action == OpAction.OTHER_CURRENCY), OnScreen()
)
async def other_currency(callback: CallbackQuery) -> None:
    await answer(callback, texts.NOT_IMPLEMENTED)


@router.message(OperationFlow.rate, F.text)
async def receive_rate(message: Message) -> None:  # pragma: no cover - stage 6
    await message.answer(texts.NOT_IMPLEMENTED)
