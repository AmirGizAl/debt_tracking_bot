"""«Долги в сомах» (TZ 13.5): four records with a client and «Кто кому должен».

client (the picker) -> amount in som, with the current debt for repayments and the early check
of the cash for «Выдал в долг» and «Я вернул» -> comment or «Пропустить» -> confirmation with
the warnings of TZ 6.6.
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
from app.bot.callbacks import LoansAction, LoansCb, MenuAction, MenuCb
from app.bot.flows import client_picker, records
from app.bot.flows.records import Event, StoredForm
from app.bot.keyboards import loans as kb
from app.bot.keyboards.records import open_record
from app.bot.notify import post_record
from app.bot.states import LoanFlow
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
from app.domain.currency import HOME_CURRENCY
from app.domain.entries import LOAN_TYPES, Book, OperationType, loan_draft
from app.domain.money import parse_amount
from app.domain.notes import optional_text
from app.domain.warnings import settlement_warning, settling_amount
from app.services import ledger, loans, obligations
from app.services.pagination import page_of

router = Router(name="loans")

PICK_FOR_LOAN = "loan"
# Records that take som out of the cash: the cash is checked as soon as the amount is known.
CASH_OUT = frozenset({OperationType.LOAN_GIVE, OperationType.LOAN_REPAY_OUT})
# Records that repay a debt: the current debt is shown before the amount (TZ 13.5 step 2).
REPAYMENTS = frozenset({OperationType.LOAN_REPAY_IN, OperationType.LOAN_REPAY_OUT})


@dataclass
class Form(StoredForm):
    request_id: str
    op_type: OperationType
    client_id: int | None = None
    client_name: str | None = None
    amount: Decimal | None = None
    comment: str | None = None

    @property
    def title(self) -> str:
        return texts.loan_title(self.op_type, self.client_name)


def _step(action: LoansAction):
    return LoansCb.filter(F.action == action)


async def _form(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> Form | None:
    return await records.current_form(Form, event, state, bot, session, user)


async def _store(state: FSMContext, form: Form) -> None:
    await state.update_data(form.dump())


# --- the screen and «Кто кому должен» ------------------------------------------------------------


async def show_loans(event: Event, state: FSMContext, bot: Bot) -> None:
    await leave_any(event, state, bot)
    await show_screen(event, bot, texts.loans_screen(), kb.screen())


@router.callback_query(MenuCb.filter(F.action == MenuAction.LOANS))
@router.callback_query(_step(LoansAction.SHOW))
async def open_loans(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await show_loans(callback, state, bot)
    await answer(callback)


@router.callback_query(_step(LoansAction.WHO_OWES))
async def who_owes(
    callback: CallbackQuery,
    callback_data: LoansCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await leave_scenario(callback, state, bot)
    lines = await obligations.loan_debts(session)
    owed = sum((line.amount for line in lines if line.amount > 0), Decimal(0))
    owing = sum((-line.amount for line in lines if line.amount < 0), Decimal(0))
    page = page_of(lines, callback_data.page)
    items = [(line.client, line.amount) for line in page.items]
    await show_screen(callback, bot, texts.loan_debts_page(items, owed, owing), kb.who_owes(page))
    await answer(callback)


# --- steps -------------------------------------------------------------------------------------


async def show_amount(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    form: Form,
    problem: str | None = None,
) -> None:
    assert form.client_id is not None and form.client_name is not None
    current = await ledger.obligation(session, form.client_id, Book.LOAN, HOME_CURRENCY)
    lines = []
    if form.op_type in REPAYMENTS:
        lines.append(texts.obligation_line(form.client_name, Book.LOAN, HOME_CURRENCY, current))
    if form.op_type in CASH_OUT:
        cash = await ledger.balance(session, HOME_CURRENCY)
        lines.append(texts.balance_line(HOME_CURRENCY, cash))
    whole = settling_amount(form.op_type, current)
    label = texts.btn_whole_amount(whole, HOME_CURRENCY) if whole is not None else None
    await state.set_state(LoanFlow.amount)
    text = texts.step_text(form.title, lines, texts.ASK_LOAN_AMOUNT, problem)
    await show_step(event, state, bot, text, kb.amount_step(label))


async def show_comment(
    event: Event, state: FSMContext, bot: Bot, form: Form, problem: str | None = None
) -> None:
    assert form.amount is not None
    await state.set_state(LoanFlow.comment)
    lines = [texts.loan_amount_line(form.amount)]
    text = texts.step_text(form.title, lines, texts.ASK_RECORD_COMMENT, problem)
    await show_step(event, state, bot, text, kb.comment_step())


async def show_confirm(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    """TZ 13.5 step 5: the new debt and cash, the warnings of TZ 6.6 for repayments."""
    assert form.client_id is not None and form.client_name is not None
    assert form.amount is not None
    draft = loan_draft(form.op_type, form.client_id, form.amount, form.comment)
    current = await ledger.obligation(session, form.client_id, Book.LOAN, HOME_CURRENCY)
    warning = settlement_warning(form.op_type, current, form.amount)
    text = texts.confirm_loan(
        form.op_type,
        form.client_name,
        form.amount,
        form.comment,
        await changes.after_lines(session, draft, form.client_name, obligations_first=True),
        texts.warning_text(warning, HOME_CURRENCY) if warning is not None else None,
    )
    await state.set_state(LoanFlow.confirm)
    await show_step(event, state, bot, text, kb.confirm())


# --- the scenario ------------------------------------------------------------------------------


@router.callback_query(_step(LoansAction.START))
async def start(
    callback: CallbackQuery,
    callback_data: LoansCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    if callback_data.op_type not in LOAN_TYPES:
        await answer(callback, texts.STALE_ACTION)
        return
    await leave_scenario(callback, state, bot)
    form = Form(request_id=str(uuid.uuid4()), op_type=callback_data.op_type)
    await state.set_data(form.dump())
    await client_picker.start(callback, state, bot, session, target=PICK_FOR_LOAN, title=form.title)
    await answer(callback)


async def _client_picked(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User, client: Client
) -> None:
    form = await _form(event, state, bot, session, user)
    if form is None:
        return
    form.client_id, form.client_name = client.id, client.name
    await _store(state, form)
    await show_amount(event, state, bot, session, form)


async def _back_to_loans(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await show_loans(event, state, bot)


client_picker.register(PICK_FOR_LOAN, client_picker.Target(_client_picked, _back_to_loans))


async def _take_amount(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    form: Form,
    amount: Decimal,
) -> None:
    if form.op_type in CASH_OUT:
        try:
            await ledger.check_available(session, {HOME_CURRENCY: -amount})
        except errors.InsufficientBalance as error:
            await show_amount(event, state, bot, session, form, texts.insufficient_balance(error))
            return
    form.amount = amount
    await _store(state, form)
    await show_comment(event, state, bot, form)


@router.message(LoanFlow.amount, F.text)
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


@router.callback_query(LoanFlow.amount, _step(LoansAction.WHOLE), OnScreen())
async def whole_amount(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    assert form.client_id is not None
    current = await ledger.obligation(session, form.client_id, Book.LOAN, HOME_CURRENCY)
    whole = settling_amount(form.op_type, current)
    if whole is None:
        # Repaid by somebody else meanwhile: show the step as it is now.
        await answer(callback, texts.STALE_ACTION)
        await show_amount(callback, state, bot, session, form)
        return
    await _take_amount(callback, state, bot, session, form, whole)
    await answer(callback)


@router.message(LoanFlow.comment, F.text)
async def receive_comment(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        form.comment = optional_text(message.text)
    except errors.TextTooLong as error:
        await show_comment(message, state, bot, form, texts.comment_too_long(error.limit))
        return
    await _store(state, form)
    await show_confirm(message, state, bot, session, form)


@router.callback_query(LoanFlow.comment, _step(LoansAction.SKIP_COMMENT), OnScreen())
async def skip_comment(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    form.comment = None
    await _store(state, form)
    await show_confirm(callback, state, bot, session, form)
    await answer(callback)


@router.callback_query(LoanFlow.confirm, _step(LoansAction.SAVE), OnScreen())
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
    assert form.client_id is not None and form.amount is not None
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        record, created = await loans.create_loan(
            session,
            user,
            uuid.UUID(form.request_id),
            form.op_type,
            form.client_id,
            form.amount,
            form.comment,
        )
    except errors.InsufficientBalance as error:
        text = texts.insufficient_balance_not_saved(error)
        await finish(bot, state, chat_id, user, session, text)
        return
    except errors.ClientNotFound:
        text = f"{texts.CLIENT_NOT_FOUND}\n{texts.RECORD_NOT_SAVED}"
        await finish(bot, state, chat_id, user, session, text)
        return
    await finish(
        bot, state, chat_id, user, session, texts.record_saved(record.id), open_record(record.id)
    )
    if created:
        await post_record(bot, settings, session, record.id)


@router.callback_query(LoanFlow.confirm, _step(LoansAction.DONT_SAVE), OnScreen())
async def dont_save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await not_saved(callback, state, bot, session, user)


@router.callback_query(StateFilter(LoanFlow), _step(LoansAction.BACK), OnScreen())
async def back(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    current = await state.get_state()
    if current == LoanFlow.confirm.state:
        await show_comment(callback, state, bot, form)
    elif current == LoanFlow.comment.state:
        await show_amount(callback, state, bot, session, form)
    else:  # the amount: back to the choice of client
        await client_picker.show_choose(callback, state, bot, session)
    await answer(callback)
