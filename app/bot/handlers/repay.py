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
from app.bot.ui import FlowOf, OnScreen, answer
from app.domain import errors
from app.domain.currency import Currency
from app.domain.money import parse_rate
from app.domain.operations import REPAY_TYPES, OperationType
from app.domain.rates import convert_payment

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
    await operation.begin(callback, state, bot, session, ENTRIES[callback_data.action])
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
async def other_currency(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    flow = await operation.load(state)
    assert flow is not None
    await operation.show_pay_currency(callback, state, bot, flow)
    await answer(callback)


@router.callback_query(
    OperationFlow.pay_currency, OpCb.filter(F.action == OpAction.PAY_CURRENCY), OnScreen()
)
async def choose_pay_currency(
    callback: CallbackQuery,
    callback_data: OpCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    flow = await operation.load(state)
    assert flow is not None
    pay_currency = Currency(callback_data.value)
    if pay_currency == flow.debt_currency:
        await answer(callback, texts.STALE_ACTION)
        return
    flow.other_currency, flow.pay_currency, flow.rate = True, pay_currency, None
    await operation.store(state, flow)
    await operation.show_amount(callback, state, bot, session, flow)
    await answer(callback)


@router.message(OperationFlow.rate, F.text)
async def receive_rate(message: Message, state: FSMContext, bot: Bot) -> None:
    assert message.text is not None
    flow = await operation.load(state)
    assert flow is not None and flow.amount is not None
    assert flow.debt_currency is not None and flow.pay_currency is not None
    try:
        rate = parse_rate(message.text)
        # Converting here catches a rate that turns the payment into 0 (TZ 4.6).
        convert_payment(flow.amount, flow.pay_currency, flow.debt_currency, rate)
    except errors.InvalidNumber as error:
        await operation.show_rate(message, state, bot, flow, texts.RATE_ERRORS[error.problem])
        return
    except errors.InvalidConversion as error:
        await operation.show_rate(message, state, bot, flow, texts.CONVERSION_ERRORS[error.problem])
        return
    flow.rate = rate
    await operation.store(state, flow)
    await operation.show_date(message, state, bot, flow)
