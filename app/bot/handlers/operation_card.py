"""Record card and cancelling a record by a mirror record (TZ 8, 12.5, 12.10)."""

import uuid

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import RecordAction, RecordCb, RevAction, RevCb
from app.bot.keyboards import operations as operations_kb
from app.bot.keyboards import records as kb
from app.bot.notify import notify_owner, post_record
from app.bot.states import ReversalFlow
from app.bot.ui import OnScreen, answer, chat_id_of, edit_or_send, finish, leave_scenario, show_step
from app.config import Settings
from app.db.models import Operation, User
from app.domain import errors
from app.domain.dates import today
from app.services import balances, cash, operations

router = Router(name="operation_card")

Event = Message | CallbackQuery


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
    try:
        operation = await operations.get_operation(session, callback_data.operation_id)
    except errors.OperationNotFound:
        await answer(callback, texts.RECORD_NOT_FOUND)
        return
    await leave_scenario(callback, state, bot)
    reversal = await operations.reversal_of(session, operation.id)
    can_cancel = operations.can_reverse(user, operation, reversal)
    await edit_or_send(
        bot,
        callback.message,
        texts.record_card(operation, reversal, settings.zone),
        kb.record_card(operation.id, operation.client_id, can_cancel),
    )
    await answer(callback)


def _refusal(operation: Operation, reversal: Operation | None) -> str:
    if operation.reversal_of_id is not None:
        return texts.CANNOT_REVERSE_REVERSAL
    if reversal is not None:
        return texts.ALREADY_REVERSED
    return texts.ONLY_AUTHOR_CAN_CANCEL


@router.callback_query(RecordCb.filter(F.action == RecordAction.REVERSE))
async def start_reversal(
    callback: CallbackQuery,
    callback_data: RecordCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    try:
        operation = await operations.get_operation(session, callback_data.operation_id)
    except errors.OperationNotFound:
        await answer(callback, texts.RECORD_NOT_FOUND)
        return
    reversal = await operations.reversal_of(session, operation.id)
    if not operations.can_reverse(user, operation, reversal):
        await answer(callback, _refusal(operation, reversal), alert=True)
        return
    if operation.cash_delta > 0:
        # Cancelling money that came in takes it back out: check before asking for a reason.
        try:
            await cash.check_available(session, operation.cash_currency, operation.cash_delta)
        except errors.InsufficientCash as error:
            await answer(callback, texts.insufficient_cash_plain(error), alert=True)
            return
    await leave_scenario(callback, state, bot)
    await state.set_state(ReversalFlow.reason)
    await state.set_data({"request_id": str(uuid.uuid4()), "operation_id": operation.id})
    await show_step(callback, state, bot, texts.ASK_CANCEL_REASON, kb.cancel_reason(operation.id))
    await answer(callback)


async def _ask_reason(
    event: Event, state: FSMContext, bot: Bot, text: str = texts.ASK_CANCEL_REASON
) -> None:
    operation_id = (await state.get_data())["operation_id"]
    await state.set_state(ReversalFlow.reason)
    await show_step(event, state, bot, text, kb.cancel_reason(operation_id))


@router.message(ReversalFlow.reason, F.text)
async def receive_reason(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    try:
        reason = cash.normalize_reason(message.text)
    except errors.EmptyText:
        await _ask_reason(message, state, bot, texts.REASON_EMPTY)
        return
    except errors.TextTooLong as error:
        await _ask_reason(message, state, bot, texts.comment_too_long(error.limit))
        return
    data = await state.update_data(reason=reason)
    try:
        operation = await operations.get_operation(session, data["operation_id"])
    except errors.OperationNotFound:
        await finish(bot, state, message.chat.id, user, texts.RECORD_NOT_FOUND)
        return
    balance = await balances.client_balance(session, operation.client_id, operation.debt_currency)
    cash_now = await cash.cash_balance(session, operation.cash_currency)
    text = texts.confirm_cancel(
        operation, reason, balance - operation.debt_delta, cash_now - operation.cash_delta
    )
    await state.set_state(ReversalFlow.confirm)
    await show_step(message, state, bot, text, kb.confirm_cancel())


@router.callback_query(ReversalFlow.confirm, RevCb.filter(F.action == RevAction.BACK), OnScreen())
async def back_to_reason(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await _ask_reason(callback, state, bot)
    await answer(callback)


@router.callback_query(
    ReversalFlow.confirm, RevCb.filter(F.action == RevAction.CONFIRM), OnScreen()
)
async def confirm_reversal(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    await answer(callback)
    data = await state.get_data()
    chat_id = chat_id_of(callback)
    operation_id = data["operation_id"]
    try:
        reversal, created = await operations.reverse_operation(
            session,
            user,
            uuid.UUID(data["request_id"]),
            operation_id,
            data["reason"],
            today(settings.zone),
        )
    except errors.InsufficientCash as error:
        await finish(bot, state, chat_id, user, texts.insufficient_cash_not_saved(error))
        return
    except errors.AlreadyReversed:
        await finish(bot, state, chat_id, user, texts.ALREADY_REVERSED)
        return
    except errors.CannotReverseReversal:
        await finish(bot, state, chat_id, user, texts.CANNOT_REVERSE_REVERSAL)
        return
    except errors.PermissionDenied:
        await finish(bot, state, chat_id, user, texts.ONLY_AUTHOR_CAN_CANCEL)
        return
    except errors.OperationNotFound:
        await finish(bot, state, chat_id, user, texts.RECORD_NOT_FOUND)
        return

    operation = await operations.get_operation(session, operation_id)
    balance = await balances.client_balance(session, operation.client_id, operation.debt_currency)
    await finish(
        bot,
        state,
        chat_id,
        user,
        texts.record_cancelled(
            operation.id, operation.client.name, balance, operation.debt_currency
        ),
    )
    if not created:
        return  # a repeated "Да, отменить": everybody has been told already
    if not user.is_owner:
        await notify_owner(
            bot,
            settings,
            texts.helper_cancelled_notice(user, operation, data["reason"]),
            operations_kb.open_record(operation.id),
        )
    await post_record(bot, settings, session, reversal.id)
