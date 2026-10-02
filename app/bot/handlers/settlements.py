"""«Ждут выдачи», «Ждут оплаты» and the payouts and receipts of exchange obligations (TZ 13.4).

A row of a list starts a payout or a receipt in the currency of the row; «Выдать» and
«Получить» on the client card start with the choice of currency. Money goes only in the
currency of the obligation: another currency is a new exchange (TZ 6.4, netting).
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb, SettleAction, SettleCb, WaitingCb
from app.bot.flows import records
from app.bot.flows.records import Event, StoredForm
from app.bot.handlers.clients import show_card, show_clients
from app.bot.keyboards import settlements as kb
from app.bot.states import SettleFlow
from app.bot.ui import (
    OnScreen,
    answer,
    chat_id_of,
    finish,
    leave_any,
    leave_scenario,
    not_saved,
    show_screen,
    show_step,
)
from app.db.models import User
from app.domain import errors
from app.domain.currency import Currency
from app.domain.entries import Book, OperationType, settlement_draft
from app.domain.money import parse_amount
from app.domain.warnings import settlement_warning, settling_amount
from app.services import clients, ledger, obligations, settlements
from app.services.pagination import page_of

router = Router(name="settlements")


@dataclass
class Form(StoredForm):
    request_id: str
    paying: bool
    client_id: int
    client_name: str
    list_page: int | None = None  # the page of the list to go back to; None: the client card
    currency: Currency | None = None
    amount: Decimal | None = None

    @property
    def op_type(self) -> OperationType:
        return OperationType.EXCHANGE_PAYOUT if self.paying else OperationType.EXCHANGE_RECEIPT

    @property
    def title(self) -> str:
        return texts.PAYOUT_TITLE if self.paying else texts.RECEIPT_TITLE


def _step(action: SettleAction):
    return SettleCb.filter(F.action == action)


async def _form(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> Form | None:
    return await records.current_form(Form, event, state, bot, session, user)


async def _store(state: FSMContext, form: Form) -> None:
    await state.update_data(form.dump())


# --- the lists ---------------------------------------------------------------------------------


async def show_waiting(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, paying: bool, number: int = 0
) -> None:
    await leave_any(event, state, bot)
    lines = await obligations.waiting(session, paying)
    text = texts.waiting_list(paying, obligations.totals(lines))
    await show_screen(event, bot, text, kb.waiting_list(paying, page_of(lines, number)))


@router.callback_query(MenuCb.filter(F.action.in_({MenuAction.TO_PAY, MenuAction.TO_RECEIVE})))
async def open_waiting(
    callback: CallbackQuery,
    callback_data: MenuCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    paying = callback_data.action == MenuAction.TO_PAY
    await show_waiting(callback, state, bot, session, paying)
    await answer(callback)


@router.callback_query(WaitingCb.filter())
async def waiting_page(
    callback: CallbackQuery,
    callback_data: WaitingCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await show_waiting(callback, state, bot, session, callback_data.paying, callback_data.page)
    await answer(callback)


# --- steps -------------------------------------------------------------------------------------


async def show_currencies(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    current = await ledger.client_obligations(session, form.client_id)
    exchange = {
        currency: amount for (book, currency), amount in current.items() if book == Book.EXCHANGE
    }
    text = texts.step_text(
        form.title, [texts.client_line(form.client_name)], texts.ASK_SETTLE_CURRENCY
    )
    await state.set_state(SettleFlow.currency)
    await show_step(event, state, bot, text, kb.currencies(exchange))


async def show_amount(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    form: Form,
    problem: str | None = None,
) -> None:
    """The current obligation (and the balance for a payout), «Всю сумму» if it settles it."""
    assert form.currency is not None
    current = await ledger.obligation(session, form.client_id, Book.EXCHANGE, form.currency)
    lines = [texts.obligation_line(form.client_name, Book.EXCHANGE, form.currency, current)]
    if form.paying:
        balance = await ledger.balance(session, form.currency)
        lines.append(texts.balance_line(form.currency, balance))
    question = texts.ask_settle_amount(form.paying, form.client_name, form.currency)
    whole = settling_amount(form.op_type, current)
    label = texts.btn_whole_amount(whole, form.currency) if whole is not None else None
    await state.set_state(SettleFlow.amount)
    text = texts.step_text(form.title, lines, question, problem)
    await show_step(event, state, bot, text, kb.amount_step(label))


async def show_confirm(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    """TZ 13.4 step 2: the new balance and obligation, the warnings of TZ 6.6."""
    assert form.currency is not None and form.amount is not None
    draft = settlement_draft(form.op_type, form.client_id, form.currency, form.amount)
    current = await ledger.obligation(session, form.client_id, Book.EXCHANGE, form.currency)
    warning = settlement_warning(form.op_type, current, form.amount)
    text = texts.confirm_settlement(
        form.paying,
        form.client_name,
        form.amount,
        form.currency,
        await records.after_lines(session, draft, form.client_name),
        texts.warning_text(warning, form.currency) if warning is not None else None,
    )
    await state.set_state(SettleFlow.confirm)
    await show_step(event, state, bot, text, kb.confirm())


# --- the scenario ------------------------------------------------------------------------------


async def _begin(
    callback: CallbackQuery,
    callback_data: SettleCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> Form | None:
    """A new payout or receipt (a fresh idempotency key); None if the client is gone."""
    try:
        client = await clients.get_client(session, callback_data.client_id)
    except errors.ClientNotFound:
        await answer(callback, texts.CLIENT_NOT_FOUND)
        return None
    await leave_scenario(callback, state, bot)
    return Form(
        request_id=str(uuid.uuid4()),
        paying=callback_data.paying,
        client_id=client.id,
        client_name=client.name,
    )


@router.callback_query(_step(SettleAction.START))
async def start_from_list(
    callback: CallbackQuery,
    callback_data: SettleCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    if callback_data.currency is None:
        await answer(callback, texts.STALE_ACTION)
        return
    form = await _begin(callback, callback_data, state, bot, session)
    if form is None:
        return
    form.list_page, form.currency = callback_data.page, callback_data.currency
    await state.set_data(form.dump())
    await show_amount(callback, state, bot, session, form)
    await answer(callback)


@router.callback_query(_step(SettleAction.FROM_CARD))
async def start_from_card(
    callback: CallbackQuery,
    callback_data: SettleCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    form = await _begin(callback, callback_data, state, bot, session)
    if form is None:
        return
    await state.set_data(form.dump())
    await show_currencies(callback, state, bot, session, form)
    await answer(callback)


@router.callback_query(SettleFlow.currency, _step(SettleAction.CURRENCY), OnScreen())
async def choose_currency(
    callback: CallbackQuery,
    callback_data: SettleCb,
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
    form.currency, form.amount = callback_data.currency, None
    await _store(state, form)
    await show_amount(callback, state, bot, session, form)
    await answer(callback)


async def _take_amount(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    form: Form,
    amount: Decimal,
) -> None:
    """A payout checks the balance as soon as the amount is known (TZ 6.5)."""
    assert form.currency is not None
    if form.paying:
        try:
            await ledger.check_available(session, {form.currency: -amount})
        except errors.InsufficientBalance as error:
            await show_amount(event, state, bot, session, form, texts.insufficient_balance(error))
            return
    form.amount = amount
    await _store(state, form)
    await show_confirm(event, state, bot, session, form)


@router.message(SettleFlow.amount, F.text)
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
        problem = texts.AMOUNT_ERRORS[error.problem]
        await show_amount(message, state, bot, session, form, problem)
        return
    await _take_amount(message, state, bot, session, form, amount)


@router.callback_query(SettleFlow.amount, _step(SettleAction.WHOLE), OnScreen())
async def whole_amount(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    assert form.currency is not None
    current = await ledger.obligation(session, form.client_id, Book.EXCHANGE, form.currency)
    whole = settling_amount(form.op_type, current)
    if whole is None:
        # Settled by somebody else meanwhile: show the step as it is now.
        await answer(callback, texts.STALE_ACTION)
        await show_amount(callback, state, bot, session, form)
        return
    await _take_amount(callback, state, bot, session, form, whole)
    await answer(callback)


@router.callback_query(SettleFlow.confirm, _step(SettleAction.SAVE), OnScreen())
async def save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    assert form.currency is not None and form.amount is not None
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        record, _created = await settlements.create_settlement(
            session,
            user,
            uuid.UUID(form.request_id),
            form.op_type,
            form.client_id,
            form.currency,
            form.amount,
        )
    except errors.InsufficientBalance as error:
        text = texts.insufficient_balance_not_saved(error)
        await finish(bot, state, chat_id, user, session, text)
        return
    except errors.ClientNotFound:
        text = f"{texts.CLIENT_NOT_FOUND}\n{texts.RECORD_NOT_SAVED}"
        await finish(bot, state, chat_id, user, session, text)
        return
    await finish(bot, state, chat_id, user, session, texts.record_saved(record.id))


@router.callback_query(SettleFlow.confirm, _step(SettleAction.DONT_SAVE), OnScreen())
async def dont_save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await not_saved(callback, state, bot, session, user)


@router.callback_query(StateFilter(SettleFlow), _step(SettleAction.BACK), OnScreen())
async def back(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    current = await state.get_state()
    if current == SettleFlow.confirm.state:
        await show_amount(callback, state, bot, session, form)
    elif current == SettleFlow.amount.state and form.list_page is not None:
        await show_waiting(callback, state, bot, session, form.paying, form.list_page)
    elif current == SettleFlow.amount.state:
        await show_currencies(callback, state, bot, session, form)
    else:  # the choice of currency: back to the client card
        await leave_scenario(callback, state, bot)
        try:
            client = await clients.get_client(session, form.client_id)
        except errors.ClientNotFound:
            await show_clients(callback, state, bot, session)
        else:
            await show_card(callback, bot, session, client)
    await answer(callback)
