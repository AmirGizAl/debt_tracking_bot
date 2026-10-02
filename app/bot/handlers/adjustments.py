"""«Корректировка» of a balance (TZ 10, 13.7). Owners only; it can never be cancelled.

currency -> «Добавить» or «Убрать» -> amount (for «Убрать» the balance is checked at once) ->
reason -> confirmation with the new balance -> save.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import changes, texts
from app.bot.callbacks import AdjustAction, AdjustCb, BalancesAction, BalancesCb
from app.bot.flows import records
from app.bot.flows.records import Event, StoredForm
from app.bot.handlers.balances import show_balances
from app.bot.keyboards import adjustments as kb
from app.bot.keyboards.records import open_record
from app.bot.notify import post_record
from app.bot.states import AdjustFlow
from app.bot.ui import OnScreen, answer, chat_id_of, finish, leave_scenario, not_saved, show_step
from app.config import Settings
from app.db.models import User
from app.domain import errors
from app.domain.currency import Currency
from app.domain.entries import adjustment_draft
from app.domain.money import parse_amount
from app.domain.notes import required_text
from app.services import adjustments, ledger

router = Router(name="adjustments")


@dataclass
class Form(StoredForm):
    request_id: str
    currency: Currency | None = None
    adding: bool | None = None
    amount: Decimal | None = None  # above zero; the direction gives the sign
    reason: str | None = None

    @property
    def change(self) -> Decimal:
        assert self.amount is not None
        return self.amount if self.adding else -self.amount


def _step(action: AdjustAction):
    return AdjustCb.filter(F.action == action)


async def _form(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> Form | None:
    return await records.current_form(Form, event, state, bot, session, user)


async def _store(state: FSMContext, form: Form) -> None:
    await state.update_data(form.dump())


# --- steps ---------------------------------------------------------------------------------------


async def show_currencies(event: Event, state: FSMContext, bot: Bot) -> None:
    await state.set_state(AdjustFlow.currency)
    text = texts.step_text(texts.ADJUST_TITLE, [], texts.ASK_ADJUST_CURRENCY)
    await show_step(event, state, bot, text, kb.currencies())


async def _balance(session: AsyncSession, currency: Currency) -> str:
    return texts.balance_line(currency, await ledger.balance(session, currency))


async def show_direction(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    assert form.currency is not None
    await state.set_state(AdjustFlow.direction)
    lines = [await _balance(session, form.currency)]
    text = texts.step_text(texts.adjust_title(form.currency), lines, texts.ASK_ADJUST_DIRECTION)
    await show_step(event, state, bot, text, kb.directions())


async def show_amount(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    form: Form,
    problem: str | None = None,
) -> None:
    assert form.currency is not None and form.adding is not None
    await state.set_state(AdjustFlow.amount)
    lines = [await _balance(session, form.currency)]
    question = texts.ask_adjust_amount(form.currency, form.adding)
    text = texts.step_text(texts.adjust_title(form.currency), lines, question, problem)
    await show_step(event, state, bot, text, kb.back_only())


async def show_reason(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    assert form.currency is not None
    await state.set_state(AdjustFlow.reason)
    lines = [texts.adjust_change(form.change, form.currency)]
    text = texts.step_text(
        texts.adjust_title(form.currency), lines, texts.ASK_ADJUST_REASON, problem
    )
    await show_step(event, state, bot, text, kb.back_only())


async def show_confirm(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    assert form.currency is not None and form.reason is not None
    draft = adjustment_draft(form.currency, form.change, form.reason)
    after = await changes.after_lines(session, draft, None)
    await state.set_state(AdjustFlow.confirm)
    text = texts.confirm_adjustment(form.change, form.currency, form.reason, after)
    await show_step(event, state, bot, text, kb.confirm())


# --- the scenario ------------------------------------------------------------------------------


@router.callback_query(BalancesCb.filter(F.action == BalancesAction.ADJUST))
async def start(callback: CallbackQuery, state: FSMContext, bot: Bot, user: User) -> None:
    if not user.is_owner:
        await answer(callback, texts.PERMISSION_DENIED, alert=True)
        return
    await leave_scenario(callback, state, bot)
    await state.set_data(Form(request_id=str(uuid.uuid4())).dump())
    await show_currencies(callback, state, bot)
    await answer(callback)


@router.callback_query(AdjustFlow.currency, _step(AdjustAction.CURRENCY), OnScreen())
async def choose_currency(
    callback: CallbackQuery,
    callback_data: AdjustCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    if callback_data.currency is None:
        await answer(callback, texts.STALE_ACTION)
        return
    form.currency, form.adding, form.amount = callback_data.currency, None, None
    await _store(state, form)
    await show_direction(callback, state, bot, session, form)
    await answer(callback)


@router.callback_query(AdjustFlow.direction, _step(AdjustAction.DIRECTION), OnScreen())
async def choose_direction(
    callback: CallbackQuery,
    callback_data: AdjustCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    form.adding, form.amount = callback_data.adding, None
    await _store(state, form)
    await show_amount(callback, state, bot, session, form)
    await answer(callback)


@router.message(AdjustFlow.amount, F.text)
async def receive_amount(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    assert form.currency is not None
    try:
        amount = parse_amount(message.text)
    except errors.InvalidNumber as error:
        problem = texts.AMOUNT_ERRORS[error.problem]
        await show_amount(message, state, bot, session, form, problem)
        return
    if not form.adding:
        # «Убрать» may not take the balance below zero (TZ 10, 6.5).
        try:
            await ledger.check_available(session, {form.currency: -amount})
        except errors.InsufficientBalance as error:
            problem = texts.insufficient_balance(error)
            await show_amount(message, state, bot, session, form, problem)
            return
    form.amount = amount
    await _store(state, form)
    await show_reason(message, state, bot, form)


@router.message(AdjustFlow.reason, F.text)
async def receive_reason(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        form.reason = required_text(message.text)
    except errors.EmptyText:
        await show_reason(message, state, bot, form, texts.REASON_EMPTY)
        return
    except errors.TextTooLong as error:
        await show_reason(message, state, bot, form, texts.comment_too_long(error.limit))
        return
    await _store(state, form)
    await show_confirm(message, state, bot, session, form)


@router.callback_query(AdjustFlow.confirm, _step(AdjustAction.SAVE), OnScreen())
async def save(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    assert form.currency is not None and form.reason is not None
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        record, created = await adjustments.create_adjustment(
            session, user, uuid.UUID(form.request_id), form.currency, form.change, form.reason
        )
    except errors.InsufficientBalance as error:
        text = texts.insufficient_balance_not_saved(error)
        await finish(bot, state, chat_id, user, session, text)
        return
    except errors.PermissionDenied:
        await finish(bot, state, chat_id, user, session, texts.PERMISSION_DENIED)
        return
    await finish(
        bot, state, chat_id, user, session, texts.record_saved(record.id), open_record(record.id)
    )
    if created:
        await post_record(bot, settings, session, record.id)


@router.callback_query(AdjustFlow.confirm, _step(AdjustAction.DONT_SAVE), OnScreen())
async def dont_save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await not_saved(callback, state, bot, session, user)


@router.callback_query(StateFilter(AdjustFlow), _step(AdjustAction.BACK), OnScreen())
async def back(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    current = await state.get_state()
    if current == AdjustFlow.confirm.state:
        await show_reason(callback, state, bot, form)
    elif current == AdjustFlow.reason.state:
        await show_amount(callback, state, bot, session, form)
    elif current == AdjustFlow.amount.state:
        await show_direction(callback, state, bot, session, form)
    elif current == AdjustFlow.direction.state:
        await show_currencies(callback, state, bot)
    else:  # the currency: back to «Балансы»
        await show_balances(callback, state, bot, session, user)
    await answer(callback)
