"""The record card, «Записи дня», the history of a client and the cancellation of a record
(TZ 11, 13.6, 13.7, 13.8).

The card and the lists are views: their buttons always work. The cancellation is a scenario:
reason -> confirmation with the balances and obligations after it -> a mirror record.
"""

import uuid
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import changes, texts
from app.bot.callbacks import (
    BalancesAction,
    BalancesCb,
    ClientsAction,
    ClientsCb,
    RecordAction,
    RecordCb,
    RecordSource,
)
from app.bot.flows import records
from app.bot.flows.records import Event, StoredForm
from app.bot.keyboards import records as kb
from app.bot.notify import notify_owners, post_record
from app.bot.states import ReversalFlow
from app.bot.ui import (
    OnScreen,
    answer,
    chat_id_of,
    finish,
    leave_any,
    leave_scenario,
    show_screen,
    show_step,
)
from app.config import Settings
from app.db.models import Operation, User
from app.domain import errors
from app.domain.entries import LOAN_TYPES, OperationType, cash_changes
from app.domain.notes import required_text
from app.services import clients, days, journal, ledger, opening, reversal

router = Router(name="records")


@dataclass
class CancelForm(StoredForm):
    request_id: str
    record_id: int
    source: RecordSource | None = None  # the list the card was opened from
    client_id: int = 0
    page: int = 0
    reason: str | None = None


async def _form(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> CancelForm | None:
    return await records.current_form(CancelForm, event, state, bot, session, user)


async def _record(
    callback: CallbackQuery, session: AsyncSession, record_id: int
) -> Operation | None:
    try:
        return await ledger.get_operation(session, record_id)
    except errors.OperationNotFound:
        await answer(callback, texts.RECORD_NOT_FOUND)
        return None


# --- lists ---------------------------------------------------------------------------------------


async def show_day_records(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, number: int = 0
) -> None:
    """«Записи дня»: the open day, the newest first (TZ 13.7)."""
    await leave_any(event, state, bot)
    day_number = await days.open_day_number(session)
    page = await journal.day_records(session, day_number, number)
    text = texts.day_records_title(day_number, page.total)
    await show_screen(event, bot, text, kb.day_records(page))


@router.callback_query(BalancesCb.filter(F.action == BalancesAction.RECORDS))
async def day_records(
    callback: CallbackQuery,
    callback_data: BalancesCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await show_day_records(callback, state, bot, session, callback_data.page)
    await answer(callback)


@router.callback_query(ClientsCb.filter(F.action == ClientsAction.HISTORY))
async def client_history(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """«История записей» of the client card: all days, the newest first."""
    try:
        client = await clients.get_client(session, callback_data.client_id)
    except errors.ClientNotFound:
        await answer(callback, texts.CLIENT_NOT_FOUND)
        return
    await leave_scenario(callback, state, bot)
    page = await journal.client_records(session, client.id, callback_data.page)
    text = texts.history_title(client.name, page.total)
    await show_screen(callback, bot, text, kb.history(client.id, page, settings.zone))
    await answer(callback)


# --- the card ------------------------------------------------------------------------------------


async def show_card(
    event: Event,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    operation: Operation,
    source: RecordSource | None = None,
    client_id: int = 0,
    page: int = 0,
) -> None:
    cancellation = await ledger.reversal_of(session, operation.id)
    frozen = operation.type == OperationType.OPENING and await opening.baseline_frozen(session)
    allowed = reversal.can_reverse(user, operation, cancellation, frozen)
    await show_screen(
        event,
        bot,
        texts.record_card(operation, cancellation, settings.zone),
        kb.record_card(operation, allowed, source, client_id, page),
    )


@router.callback_query(RecordCb.filter(F.action == RecordAction.OPEN))
async def open_record(
    callback: CallbackQuery,
    callback_data: RecordCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    operation = await _record(callback, session, callback_data.record_id)
    if operation is None:
        return
    await leave_scenario(callback, state, bot)
    await show_card(
        callback,
        bot,
        session,
        user,
        settings,
        operation,
        callback_data.source,
        callback_data.client_id,
        callback_data.page,
    )
    await answer(callback)


# --- cancellation --------------------------------------------------------------------------------


def _refusal(operation: Operation, cancellation: Operation | None, frozen: bool) -> str:
    """Why «Отменить запись» does nothing (TZ 11.1); the button is hidden in these cases."""
    if operation.reversal_of_id is not None:
        return texts.CANNOT_REVERSE_REVERSAL
    if cancellation is not None:
        return texts.ALREADY_REVERSED
    if operation.type == OperationType.ADJUSTMENT:
        return texts.CANNOT_REVERSE_ADJUSTMENT
    if operation.type == OperationType.OPENING and frozen:
        return texts.OPENING_FROZEN
    return texts.ONLY_AUTHOR_CAN_CANCEL


async def _show_reason(
    event: Event, state: FSMContext, bot: Bot, operation: Operation, problem: str | None = None
) -> None:
    await state.set_state(ReversalFlow.reason)
    text = texts.step_text(texts.cancel_title(operation), [], texts.ASK_CANCEL_REASON, problem)
    await show_step(event, state, bot, text, kb.cancel_reason())


async def _show_confirm(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    operation: Operation,
    reason: str,
) -> None:
    client_name = operation.client.name if operation.client is not None else None
    after = await changes.after_lines(
        session,
        reversal.mirror(operation),
        client_name,
        obligations_first=operation.type in LOAN_TYPES,
    )
    await state.set_state(ReversalFlow.confirm)
    text = texts.confirm_cancel(operation, reason, after)
    await show_step(event, state, bot, text, kb.confirm_cancel())


@router.callback_query(RecordCb.filter(F.action == RecordAction.CANCEL))
async def start_cancel(
    callback: CallbackQuery,
    callback_data: RecordCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    operation = await _record(callback, session, callback_data.record_id)
    if operation is None:
        return
    cancellation = await ledger.reversal_of(session, operation.id)
    frozen = operation.type == OperationType.OPENING and await opening.baseline_frozen(session)
    if not reversal.can_reverse(user, operation, cancellation, frozen):
        await answer(callback, _refusal(operation, cancellation, frozen), alert=True)
        return
    try:
        # Cancelling money that came in takes it out again: checked before the reason is typed.
        await ledger.check_available(session, cash_changes(reversal.mirror(operation).entries))
    except errors.InsufficientBalance as error:
        await answer(callback, texts.insufficient_balance_not_cancelled(error), alert=True)
        return
    await leave_scenario(callback, state, bot)
    form = CancelForm(
        request_id=str(uuid.uuid4()),
        record_id=operation.id,
        source=callback_data.source,
        client_id=callback_data.client_id,
        page=callback_data.page,
    )
    await state.set_data(form.dump())
    await _show_reason(callback, state, bot, operation)
    await answer(callback)


@router.message(ReversalFlow.reason, F.text)
async def receive_reason(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    operation = await ledger.get_operation(session, form.record_id)
    try:
        form.reason = required_text(message.text)
    except errors.EmptyText:
        await _show_reason(message, state, bot, operation, texts.REASON_EMPTY)
        return
    except errors.TextTooLong as error:
        await _show_reason(message, state, bot, operation, texts.comment_too_long(error.limit))
        return
    await state.update_data(form.dump())
    await _show_confirm(message, state, bot, session, operation, form.reason)


@router.callback_query(
    StateFilter(ReversalFlow), RecordCb.filter(F.action == RecordAction.BACK), OnScreen()
)
async def back(
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
    operation = await ledger.get_operation(session, form.record_id)
    if await state.get_state() == ReversalFlow.confirm.state:
        await _show_reason(callback, state, bot, operation)
    else:  # the reason: back to the card
        await leave_scenario(callback, state, bot)
        await show_card(
            callback,
            bot,
            session,
            user,
            settings,
            operation,
            form.source,
            form.client_id,
            form.page,
        )
    await answer(callback)


@router.callback_query(
    ReversalFlow.confirm, RecordCb.filter(F.action == RecordAction.CONFIRM), OnScreen()
)
async def confirm(
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
    assert form.reason is not None
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        cancellation, created = await reversal.reverse(
            session, user, uuid.UUID(form.request_id), form.record_id, form.reason
        )
    except errors.InsufficientBalance as error:
        text = texts.insufficient_balance_not_cancelled(error)
        await finish(bot, state, chat_id, user, session, text)
        return
    except errors.AlreadyReversed:
        await finish(bot, state, chat_id, user, session, texts.ALREADY_REVERSED)
        return
    except errors.CannotReverse as error:
        text = (
            texts.CANNOT_REVERSE_REVERSAL
            if error.reason == errors.CannotReverseReason.REVERSAL
            else texts.CANNOT_REVERSE_ADJUSTMENT
        )
        await finish(bot, state, chat_id, user, session, text)
        return
    except errors.BaselineFrozen:
        text = f"{texts.OPENING_FROZEN}\n{texts.RECORD_NOT_CANCELLED}"
        await finish(bot, state, chat_id, user, session, text)
        return
    except errors.PermissionDenied:
        await finish(bot, state, chat_id, user, session, texts.ONLY_AUTHOR_CAN_CANCEL)
        return
    await finish(
        bot,
        state,
        chat_id,
        user,
        session,
        texts.record_cancelled(form.record_id, cancellation.id),
        kb.open_record(form.record_id),
    )
    if created:
        if not user.is_owner:
            # TZ 11.7, 13.11: every owner hears about a cancellation by a helper.
            original = await ledger.get_operation(session, form.record_id)
            notice = texts.helper_cancelled_notice(user, original, form.reason)
            await notify_owners(bot, session, notice, kb.open_record(original.id))
        await post_record(bot, settings, session, cancellation.id)
