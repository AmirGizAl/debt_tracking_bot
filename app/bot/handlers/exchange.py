"""«Обмен» (TZ 6.4, 13.3). Every step requires its FSM state and the current screen."""

import uuid
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import ExchangeAction, ExchangeCb, MenuAction, MenuCb
from app.bot.flows import client_picker
from app.bot.flows import exchange as flow
from app.bot.flows.exchange import Event, Form
from app.bot.keyboards.common import main_menu
from app.bot.states import ExchangeFlow
from app.bot.ui import OnScreen, answer, chat_id_of, edit_or_send, finish, menu_text
from app.db.models import Client, User
from app.domain import errors
from app.domain.currency import Currency
from app.domain.entries import exchange_cash_changes
from app.domain.money import parse_amount, parse_rate
from app.domain.notes import optional_text
from app.domain.rates import convert
from app.services import exchange, ledger

router = Router(name="exchange")


def _step(action: ExchangeAction):
    return ExchangeCb.filter(F.action == action)


async def _form(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> Form | None:
    """The scenario data, or None (and the menu) if it is gone, e.g. after a restart."""
    form = await flow.load(state)
    if form is None:
        if isinstance(event, CallbackQuery):
            await answer(event, texts.STALE_ACTION)
        await finish(bot, state, chat_id_of(event), user, session, texts.STALE_ACTION)
    return form


@router.callback_query(MenuCb.filter(F.action == MenuAction.EXCHANGE))
async def start(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await flow.begin(callback, state, bot)
    await answer(callback)


# --- currencies and amounts ------------------------------------------------------------------


@router.callback_query(ExchangeFlow.give_currency, _step(ExchangeAction.GIVE), OnScreen())
async def choose_give(
    callback: CallbackQuery,
    callback_data: ExchangeCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    form = Form(request_id=form.request_id, give_currency=Currency(callback_data.value))
    await state.set_data({**(await state.get_data()), **form.dump()})
    await flow.show_get_currency(callback, state, bot, form)
    await answer(callback)


@router.callback_query(ExchangeFlow.get_currency, _step(ExchangeAction.GET), OnScreen())
async def choose_get(
    callback: CallbackQuery,
    callback_data: ExchangeCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    form.get_currency = Currency(callback_data.value)
    form.side, form.give_amount, form.get_amount, form.rate = "give", None, None, None
    await flow.store(state, form)
    await flow.show_amount(callback, state, bot, form)
    await answer(callback)


@router.callback_query(ExchangeFlow.amount, _step(ExchangeAction.SWITCH_SIDE), OnScreen())
async def switch_side(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    form.side = form.other_side
    form.give_amount = form.get_amount = None
    await flow.store(state, form)
    await flow.show_amount(callback, state, bot, form)
    await answer(callback)


@router.message(ExchangeFlow.amount, F.text)
async def receive_amount(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        amount = parse_amount(message.text)
    except errors.InvalidNumber as error:
        await flow.show_amount(message, state, bot, form, texts.AMOUNT_ERRORS[error.problem])
        return
    form.set_amount(form.side, amount)
    form.set_amount(form.other_side, None)
    await flow.store(state, form)
    if form.same_currency:
        await flow.show_second_amount(message, state, bot, form)
    else:
        await flow.show_rate(message, state, bot, session, form)


async def _apply_rate(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form, rate: Decimal
) -> None:
    typed = form.amount_of(form.side)
    assert typed is not None
    try:
        other = convert(typed, form.typed_currency, form.other_currency, rate)
    except errors.InvalidConversion as error:
        problem = texts.CONVERSION_ERRORS[error.problem]
        await flow.show_rate(event, state, bot, session, form, problem)
        return
    form.rate = rate
    form.set_amount(form.other_side, other)
    await flow.store(state, form)
    await flow.show_mode(event, state, bot, form)


@router.message(ExchangeFlow.rate, F.text)
async def receive_rate(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        rate = parse_rate(message.text)
    except errors.InvalidNumber as error:
        problem = texts.RATE_ERRORS[error.problem]
        await flow.show_rate(message, state, bot, session, form, problem)
        return
    await _apply_rate(message, state, bot, session, form, rate)


@router.callback_query(ExchangeFlow.rate, _step(ExchangeAction.LAST_RATE), OnScreen())
async def use_last_rate(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    assert form.give_currency is not None and form.get_currency is not None
    rate = await exchange.last_rate_today(session, form.give_currency, form.get_currency)
    if rate is None:
        await answer(callback, texts.STALE_ACTION)
        return
    await _apply_rate(callback, state, bot, session, form, rate)
    await answer(callback)


@router.message(ExchangeFlow.second_amount, F.text)
async def receive_second_amount(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        amount = parse_amount(message.text)
    except errors.InvalidNumber as error:
        problem = texts.AMOUNT_ERRORS[error.problem]
        await flow.show_second_amount(message, state, bot, form, problem)
        return
    form.set_amount(form.other_side, amount)
    await flow.store(state, form)
    await flow.show_mode(message, state, bot, form)


# --- how it goes and the client --------------------------------------------------------------


async def _problem(session: AsyncSession, form: Form) -> str | None:
    """Nothing to record, or not enough money for the part paid now (TZ 6.4, 6.5)."""
    terms = form.terms()
    if form.same_currency and terms.give_amount == terms.get_amount and terms.instant:
        return texts.NOTHING_TO_EXCHANGE
    try:
        await ledger.check_available(session, exchange_cash_changes(terms))
    except errors.InsufficientBalance as error:
        return texts.insufficient_balance(error)
    return None


@router.callback_query(ExchangeFlow.mode, _step(ExchangeAction.MODE), OnScreen())
async def choose_mode(
    callback: CallbackQuery,
    callback_data: ExchangeCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    if callback_data.value not in flow.MODES:
        await answer(callback, texts.STALE_ACTION)
        return
    form.received_now, form.paid_now = flow.MODES[callback_data.value]
    problem = await _problem(session, form)
    if problem is not None:
        form.received_now = form.paid_now = None
        await flow.store(state, form)
        await flow.show_mode(callback, state, bot, form, problem)
        await answer(callback)
        return
    await flow.store(state, form)
    if form.instant:
        await flow.show_confirm(callback, state, bot, session, form)
    else:
        await flow.show_client_step(callback, state, bot, session, form)
    await answer(callback)


async def _client_picked(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User, client: Client
) -> None:
    form = await _form(event, state, bot, session, user)
    if form is None:
        return
    form.client_id, form.client_name = client.id, client.name
    await flow.store(state, form)
    await flow.show_confirm(event, state, bot, session, form)


async def _back_to_mode(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(event, state, bot, session, user)
    if form is not None:
        await flow.show_mode(event, state, bot, form)


async def _back_to_confirm(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(event, state, bot, session, user)
    if form is not None:
        await flow.show_confirm(event, state, bot, session, form)


client_picker.register(flow.PICK_FOR_DEAL, client_picker.Target(_client_picked, _back_to_mode))
client_picker.register(
    flow.PICK_FOR_CONFIRM, client_picker.Target(_client_picked, _back_to_confirm)
)


# --- confirmation --------------------------------------------------------------------------------


@router.callback_query(ExchangeFlow.confirm, _step(ExchangeAction.SET_CLIENT), OnScreen())
async def set_client(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    await client_picker.start(
        callback, state, bot, session, target=flow.PICK_FOR_CONFIRM, title=flow.summary(form)
    )
    await answer(callback)


@router.callback_query(ExchangeFlow.confirm, _step(ExchangeAction.EDIT_AMOUNT), OnScreen())
async def ask_new_amount(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    await flow.show_edit_amount(callback, state, bot, form)
    await answer(callback)


@router.message(ExchangeFlow.edit_amount, F.text)
async def receive_new_amount(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    # A calculated amount rounded to banknotes; the rate stays as entered (TZ 6.4).
    assert message.text is not None
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        amount = parse_amount(message.text)
    except errors.InvalidNumber as error:
        await flow.show_edit_amount(message, state, bot, form, texts.AMOUNT_ERRORS[error.problem])
        return
    previous = form.amount_of(form.other_side)
    form.set_amount(form.other_side, amount)
    problem = await _problem(session, form)
    if problem is not None:
        form.set_amount(form.other_side, previous)
        await flow.show_edit_amount(message, state, bot, form, problem)
        return
    await flow.store(state, form)
    await flow.show_confirm(message, state, bot, session, form)


@router.callback_query(ExchangeFlow.confirm, _step(ExchangeAction.COMMENT), OnScreen())
async def ask_comment(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if await _form(callback, state, bot, session, user) is None:
        return
    await flow.show_comment(callback, state, bot)
    await answer(callback)


@router.message(ExchangeFlow.comment, F.text)
async def receive_comment(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        form.comment = optional_text(message.text)
    except errors.TextTooLong as error:
        await flow.show_comment(message, state, bot, texts.comment_too_long(error.limit))
        return
    await flow.store(state, form)
    await flow.show_confirm(message, state, bot, session, form)


@router.callback_query(ExchangeFlow.confirm, _step(ExchangeAction.SAVE), OnScreen())
async def save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        record, _created = await exchange.create_exchange(
            session, user, uuid.UUID(form.request_id), form.terms(), form.client_id, form.comment
        )
    except errors.InsufficientBalance as error:
        await finish(
            bot, state, chat_id, user, session, texts.insufficient_balance_not_saved(error)
        )
        return
    except errors.ClientNotFound:
        text = f"{texts.CLIENT_NOT_FOUND}\n{texts.RECORD_NOT_SAVED}"
        await finish(bot, state, chat_id, user, session, text)
        return
    await finish(bot, state, chat_id, user, session, texts.record_saved(record.id))


@router.callback_query(ExchangeFlow.confirm, _step(ExchangeAction.DONT_SAVE), OnScreen())
async def dont_save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert callback.message is not None
    await state.clear()
    await edit_or_send(bot, callback.message, await menu_text(session), main_menu(user))
    await answer(callback, texts.RECORD_NOT_SAVED)


@router.callback_query(StateFilter(ExchangeFlow), _step(ExchangeAction.BACK), OnScreen())
async def back(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    await flow.go_back(callback, state, bot, session, form)
    await answer(callback)
