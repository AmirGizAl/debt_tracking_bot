"""Cash: balances, movements, owner's manual adjustments (TZ 12.7)."""

import uuid
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import AdjAction, AdjCb, CashAction, CashCb, MenuAction, MenuCb
from app.bot.keyboards import cash as kb
from app.bot.keyboards.common import main_menu
from app.bot.notify import post_adjustment
from app.bot.states import AdjustmentFlow
from app.bot.ui import (
    OnScreen,
    answer,
    chat_id_of,
    edit_or_send,
    finish,
    leave_any,
    leave_scenario,
    show_screen,
    show_step,
)
from app.config import Settings
from app.db.models import User
from app.domain import errors
from app.domain.currency import Currency
from app.domain.dates import today
from app.domain.money import parse_amount
from app.services import cash

router = Router(name="cash")

Event = Message | CallbackQuery


# --- screens -----------------------------------------------------------------------------------


async def show_cash(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await leave_any(event, state, bot)
    balances = await cash.cash_balances(session)
    await show_screen(event, bot, texts.cash_screen(balances), kb.cash_screen(user))


@router.callback_query(MenuCb.filter(F.action == MenuAction.CASH))
@router.callback_query(CashCb.filter(F.action == CashAction.SHOW))
async def open_cash(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await show_cash(callback, state, bot, session, user)
    await answer(callback)


@router.callback_query(CashCb.filter(F.action == CashAction.MOVEMENTS))
async def show_movements(
    callback: CallbackQuery,
    callback_data: CashCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await leave_scenario(callback, state, bot)
    page = await cash.movements(session, callback_data.page)
    text = texts.MOVEMENTS_TITLE
    if page.total == 0:
        text += f"\n{texts.MOVEMENTS_EMPTY}"
    await edit_or_send(bot, callback.message, text, kb.movements(page))
    await answer(callback)


@router.callback_query(CashCb.filter(F.action == CashAction.ADJUSTMENT_INFO))
async def adjustment_info(
    callback: CallbackQuery, callback_data: CashCb, session: AsyncSession, settings: Settings
) -> None:
    adjustment = await cash.get_adjustment(session, callback_data.item_id)
    if adjustment is None:
        await answer(callback, texts.STALE_ACTION)
        return
    await answer(callback, texts.adjustment_popup(adjustment, settings.zone), alert=True)


# --- adjustment scenario (owner only) ----------------------------------------------------------


async def _data(state: FSMContext) -> tuple[Currency, bool, Decimal | None]:
    data = await state.get_data()
    amount = data.get("amount")
    return (
        Currency(data["currency"]),
        bool(data.get("adding")),
        Decimal(amount) if amount is not None else None,
    )


async def _ask_currency(event: Event, state: FSMContext, bot: Bot) -> None:
    await state.set_state(AdjustmentFlow.currency)
    await show_step(event, state, bot, texts.ASK_ADJUST_CURRENCY, kb.adjust_currency())


async def _ask_direction(event: Event, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    currency, _, _ = await _data(state)
    available = await cash.cash_balance(session, currency)
    await state.set_state(AdjustmentFlow.direction)
    await show_step(
        event, state, bot, texts.ask_adjust_direction(currency, available), kb.adjust_direction()
    )


async def _ask_amount(
    event: Event, state: FSMContext, bot: Bot, problem: str | None = None
) -> None:
    currency, adding, _ = await _data(state)
    text = (
        texts.adjust_amount_problem(currency, problem)
        if problem
        else texts.ask_adjust_amount(currency, adding)
    )
    await state.set_state(AdjustmentFlow.amount)
    await show_step(event, state, bot, text, kb.adjust_back())


async def _ask_reason(
    event: Event, state: FSMContext, bot: Bot, text: str = texts.ASK_ADJUST_REASON
) -> None:
    await state.set_state(AdjustmentFlow.reason)
    await show_step(event, state, bot, text, kb.adjust_back())


async def _show_confirmation(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    currency, adding, amount = await _data(state)
    assert amount is not None
    signed = amount if adding else -amount
    reason = (await state.get_data())["reason"]
    after = await cash.cash_balance(session, currency) + signed
    await state.set_state(AdjustmentFlow.confirm)
    await show_step(
        event,
        state,
        bot,
        texts.confirm_adjustment(currency, signed, reason, after),
        kb.adjust_confirm(),
    )


@router.callback_query(CashCb.filter(F.action == CashAction.ADJUST))
async def start_adjustment(
    callback: CallbackQuery, state: FSMContext, bot: Bot, user: User
) -> None:
    if not user.is_owner:
        await answer(callback, texts.PERMISSION_DENIED, alert=True)
        return
    await leave_scenario(callback, state, bot)
    await state.set_data({"request_id": str(uuid.uuid4())})
    await _ask_currency(callback, state, bot)
    await answer(callback)


@router.callback_query(
    AdjustmentFlow.currency, AdjCb.filter(F.action == AdjAction.CURRENCY), OnScreen()
)
async def choose_currency(
    callback: CallbackQuery,
    callback_data: AdjCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await state.update_data(currency=str(Currency(callback_data.value)))
    await _ask_direction(callback, state, bot, session)
    await answer(callback)


@router.callback_query(
    AdjustmentFlow.direction,
    AdjCb.filter(F.action.in_({AdjAction.ADD, AdjAction.REMOVE})),
    OnScreen(),
)
async def choose_direction(
    callback: CallbackQuery, callback_data: AdjCb, state: FSMContext, bot: Bot
) -> None:
    await state.update_data(adding=callback_data.action == AdjAction.ADD)
    await _ask_amount(callback, state, bot)
    await answer(callback)


@router.message(AdjustmentFlow.amount, F.text)
async def receive_amount(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    assert message.text is not None
    currency, adding, _ = await _data(state)
    try:
        amount = parse_amount(message.text)
    except errors.InvalidNumber as error:
        await _ask_amount(message, state, bot, texts.AMOUNT_ERRORS[error.problem])
        return
    if not adding:
        # "Убрать" cannot make the cash negative (TZ 12.7); checked again when saving.
        try:
            await cash.check_available(session, currency, amount)
        except errors.InsufficientCash as error:
            await _ask_amount(message, state, bot, texts.insufficient_cash_retry(error))
            return
    await state.update_data(amount=str(amount))
    await _ask_reason(message, state, bot)


@router.message(AdjustmentFlow.reason, F.text)
async def receive_reason(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    try:
        reason = cash.normalize_reason(message.text)
    except errors.EmptyText:
        await _ask_reason(message, state, bot, texts.REASON_EMPTY)
        return
    except errors.TextTooLong as error:
        await _ask_reason(message, state, bot, texts.comment_too_long(error.limit))
        return
    await state.update_data(reason=reason)
    await _show_confirmation(message, state, bot, session)


@router.callback_query(AdjustmentFlow.confirm, AdjCb.filter(F.action == AdjAction.SAVE), OnScreen())
async def save(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    await answer(callback)
    data = await state.get_data()
    currency, adding, amount = await _data(state)
    assert amount is not None
    chat_id = chat_id_of(callback)
    try:
        adjustment, created = await cash.create_adjustment(
            session,
            user,
            uuid.UUID(data["request_id"]),
            currency,
            amount if adding else -amount,
            data["reason"],
            today(settings.zone),
        )
    except errors.InsufficientCash as error:
        await finish(bot, state, chat_id, user, texts.insufficient_cash_not_saved(error))
        return
    after = await cash.cash_balance(session, currency)
    await finish(bot, state, chat_id, user, texts.adjustment_saved(currency, after))
    if created:
        await post_adjustment(bot, settings, session, adjustment.id)


@router.callback_query(
    AdjustmentFlow.confirm, AdjCb.filter(F.action == AdjAction.DONT_SAVE), OnScreen()
)
async def dont_save(callback: CallbackQuery, state: FSMContext, bot: Bot, user: User) -> None:
    assert callback.message is not None
    await state.clear()
    await edit_or_send(bot, callback.message, texts.MAIN_MENU, main_menu(user))
    await answer(callback, texts.RECORD_NOT_SAVED)


@router.callback_query(
    StateFilter(AdjustmentFlow), AdjCb.filter(F.action == AdjAction.BACK), OnScreen()
)
async def back(callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    current = await state.get_state()
    if current == AdjustmentFlow.direction.state:
        await _ask_currency(callback, state, bot)
    elif current == AdjustmentFlow.amount.state:
        await _ask_direction(callback, state, bot, session)
    elif current == AdjustmentFlow.reason.state:
        await _ask_amount(callback, state, bot)
    elif current == AdjustmentFlow.confirm.state:
        await _ask_reason(callback, state, bot)
    await answer(callback)
