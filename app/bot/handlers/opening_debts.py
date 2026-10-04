"""«Начальные долги» in the settings (agreed with the customer on 03.10.2026). Owners only.

client (the picker) -> currency -> for KGS a som loan or an obligation of the exchanges ->
who owes -> amount -> confirmation. Balances do not change; one debt that is not cancelled
per client, book and currency. A mistake is fixed by cancelling the record from its card.
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
from app.bot.callbacks import OpeningDebtAction, OpeningDebtCb
from app.bot.flows import client_picker, records
from app.bot.flows.records import Event, StoredForm
from app.bot.keyboards import opening_debts as kb
from app.bot.keyboards.records import open_record
from app.bot.notify import post_record
from app.bot.states import OpeningDebtFlow
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
from app.config import Settings
from app.db.models import Client, User
from app.domain import errors
from app.domain.currency import HOME_CURRENCY, Currency
from app.domain.entries import Book, opening_debt_draft
from app.domain.money import parse_amount
from app.services import opening_debts
from app.services.pagination import page_of

router = Router(name="opening_debts")

PICK_FOR_DEBT = "opening_debt"


@dataclass
class Form(StoredForm):
    request_id: str
    client_id: int | None = None
    client_name: str | None = None
    currency: Currency | None = None
    book: Book | None = None
    owed: bool | None = None  # the client owes us
    amount: Decimal | None = None  # above zero; `owed` gives the sign

    @property
    def signed(self) -> Decimal:
        assert self.amount is not None
        return self.amount if self.owed else -self.amount

    def head(self) -> list[str]:
        """What is chosen so far, above the question of a step."""
        lines = []
        if self.client_name is not None:
            lines.append(texts.client_line(self.client_name))
        if self.currency is not None:
            lines.append(f"Валюта: {self.currency}")
        if self.book is not None and self.currency == HOME_CURRENCY:
            lines.append(texts.book_line(self.book))
        if self.owed is not None:
            lines.append(texts.BTN_OWED_TO_US if self.owed else texts.BTN_WE_OWE)
        return lines


def _step(action: OpeningDebtAction):
    return OpeningDebtCb.filter(F.action == action)


async def _form(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> Form | None:
    return await records.current_form(Form, event, state, bot, session, user)


async def _store(state: FSMContext, form: Form) -> None:
    await state.update_data(form.dump())


async def _owner_only(callback: CallbackQuery, user: User) -> bool:
    if user.is_owner:
        return True
    await answer(callback, texts.PERMISSION_DENIED, alert=True)
    return False


# --- the screen ----------------------------------------------------------------------------------


async def show_debts(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, number: int = 0
) -> None:
    await leave_any(event, state, bot)
    debts = await opening_debts.active_debts(session)
    text = texts.opening_debts_screen(len(debts))
    await show_screen(event, bot, text, kb.screen(page_of(debts, number)))


@router.callback_query(_step(OpeningDebtAction.SHOW))
async def open_screen(
    callback: CallbackQuery,
    callback_data: OpeningDebtCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    if not await _owner_only(callback, user):
        return
    await show_debts(callback, state, bot, session, callback_data.page)
    await answer(callback)


# --- steps ---------------------------------------------------------------------------------------


def _text(form: Form, question: str, problem: str | None = None) -> str:
    return texts.step_text(texts.OPENING_DEBT_TITLE, form.head(), question, problem)


async def show_currency(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    await state.set_state(OpeningDebtFlow.currency)
    await show_step(
        event, state, bot, _text(form, texts.ASK_DEBT_CURRENCY, problem), kb.currencies()
    )


async def show_book(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    await state.set_state(OpeningDebtFlow.book)
    await show_step(event, state, bot, _text(form, texts.ASK_DEBT_BOOK, problem), kb.books())


async def show_direction(event: Event, state: FSMContext, bot: Bot, form: Form) -> None:
    await state.set_state(OpeningDebtFlow.direction)
    await show_step(event, state, bot, _text(form, texts.ASK_DEBT_DIRECTION), kb.directions())


async def show_amount(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    assert form.currency is not None
    await state.set_state(OpeningDebtFlow.amount)
    question = texts.ask_debt_amount(form.currency)
    await show_step(event, state, bot, _text(form, question, problem), kb.back_only())


async def show_confirm(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    assert form.client_name is not None and form.book is not None
    assert form.currency is not None and form.amount is not None
    draft = opening_debt_draft(form.client_id, form.book, form.currency, form.signed)
    after = await changes.after_lines(session, draft, form.client_name, obligations_first=True)
    text = texts.confirm_opening_debt(
        form.client_name, form.book, form.currency, form.signed, after
    )
    await state.set_state(OpeningDebtFlow.confirm)
    await show_step(event, state, bot, text, kb.confirm())


async def _taken(session: AsyncSession, form: Form) -> str | None:
    """The client has a debt in this book and currency already: say so on the step."""
    assert form.client_id is not None and form.client_name is not None
    assert form.book is not None and form.currency is not None
    if await opening_debts.active_debt(session, form.client_id, form.book, form.currency):
        return texts.opening_debt_exists(form.client_name, form.currency)
    return None


# --- the scenario ------------------------------------------------------------------------------


@router.callback_query(_step(OpeningDebtAction.ENTER))
async def enter(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if not await _owner_only(callback, user):
        return
    await leave_scenario(callback, state, bot)
    await state.set_data(Form(request_id=str(uuid.uuid4())).dump())
    await client_picker.start(
        callback, state, bot, session, target=PICK_FOR_DEBT, title=texts.OPENING_DEBT_TITLE
    )
    await answer(callback)


async def _client_picked(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User, client: Client
) -> None:
    form = await _form(event, state, bot, session, user)
    if form is None:
        return
    form.client_id, form.client_name = client.id, client.name
    await _store(state, form)
    await show_currency(event, state, bot, form)


async def _back_to_debts(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await show_debts(event, state, bot, session)


client_picker.register(PICK_FOR_DEBT, client_picker.Target(_client_picked, _back_to_debts))


@router.callback_query(OpeningDebtFlow.currency, _step(OpeningDebtAction.CURRENCY), OnScreen())
async def choose_currency(
    callback: CallbackQuery,
    callback_data: OpeningDebtCb,
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
    form.currency, form.book, form.owed, form.amount = callback_data.currency, None, None, None
    if form.currency == HOME_CURRENCY:
        await _store(state, form)
        await show_book(callback, state, bot, form)
    else:
        # Debts in other currencies are obligations of the exchanges (03.10.2026).
        form.book = Book.EXCHANGE
        problem = await _taken(session, form)
        if problem is not None:
            form.currency = form.book = None
            await _store(state, form)
            await show_currency(callback, state, bot, form, problem)
        else:
            await _store(state, form)
            await show_direction(callback, state, bot, form)
    await answer(callback)


@router.callback_query(OpeningDebtFlow.book, _step(OpeningDebtAction.BOOK), OnScreen())
async def choose_book(
    callback: CallbackQuery,
    callback_data: OpeningDebtCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    if callback_data.book is None:
        await answer(callback, texts.STALE_ACTION)
        return
    form.book = callback_data.book
    problem = await _taken(session, form)
    if problem is not None:
        form.book = None
        await _store(state, form)
        await show_book(callback, state, bot, form, problem)
    else:
        await _store(state, form)
        await show_direction(callback, state, bot, form)
    await answer(callback)


@router.callback_query(OpeningDebtFlow.direction, _step(OpeningDebtAction.DIRECTION), OnScreen())
async def choose_direction(
    callback: CallbackQuery,
    callback_data: OpeningDebtCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    form.owed, form.amount = callback_data.owed, None
    await _store(state, form)
    await show_amount(callback, state, bot, form)
    await answer(callback)


@router.message(OpeningDebtFlow.amount, F.text)
async def receive_amount(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        form.amount = parse_amount(message.text)
    except errors.InvalidNumber as error:
        await show_amount(message, state, bot, form, texts.AMOUNT_ERRORS[error.problem])
        return
    await _store(state, form)
    await show_confirm(message, state, bot, session, form)


@router.callback_query(OpeningDebtFlow.confirm, _step(OpeningDebtAction.SAVE), OnScreen())
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
    assert form.client_id is not None and form.client_name is not None
    assert form.book is not None and form.currency is not None
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        record, created = await opening_debts.create_opening_debt(
            session,
            user,
            uuid.UUID(form.request_id),
            form.client_id,
            form.book,
            form.currency,
            form.signed,
        )
    except errors.OpeningDebtExists:
        text = (
            f"{texts.opening_debt_exists(form.client_name, form.currency)}\n"
            f"{texts.RECORD_NOT_SAVED}"
        )
        await finish(bot, state, chat_id, user, session, text)
        return
    except errors.ClientNotFound:
        text = f"{texts.CLIENT_NOT_FOUND}\n{texts.RECORD_NOT_SAVED}"
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


@router.callback_query(OpeningDebtFlow.confirm, _step(OpeningDebtAction.DONT_SAVE), OnScreen())
async def dont_save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await not_saved(callback, state, bot, session, user)


@router.callback_query(StateFilter(OpeningDebtFlow), _step(OpeningDebtAction.BACK), OnScreen())
async def back(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    current = await state.get_state()
    if current == OpeningDebtFlow.confirm.state:
        await show_amount(callback, state, bot, form)
    elif current == OpeningDebtFlow.amount.state:
        form.owed = None
        await _store(state, form)
        await show_direction(callback, state, bot, form)
    elif current == OpeningDebtFlow.direction.state and form.currency == HOME_CURRENCY:
        form.book = None
        await _store(state, form)
        await show_book(callback, state, bot, form)
    elif current in (OpeningDebtFlow.direction.state, OpeningDebtFlow.book.state):
        form.currency = form.book = None
        await _store(state, form)
        await show_currency(callback, state, bot, form)
    else:  # the currency: back to the choice of client
        await client_picker.show_choose(callback, state, bot, session)
    await answer(callback)
