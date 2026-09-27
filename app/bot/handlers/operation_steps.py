"""Steps shared by the four record scenarios (TZ 12.2-12.4).

Every callback here requires the matching FSM state and the current scenario screen
(`OnScreen`), so buttons of older messages are answered as stale by the fallback router.
"""

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import OpAction, OpCb
from app.bot.flows import operation
from app.bot.flows.operation import Event, Flow
from app.bot.keyboards import operations as kb
from app.bot.keyboards.common import main_menu
from app.bot.states import OperationFlow
from app.bot.ui import OnScreen, answer, chat_id_of, edit_or_send, finish
from app.config import Settings
from app.db.models import User
from app.domain import errors
from app.domain.dates import parse_date, today, yesterday
from app.domain.money import parse_amount
from app.domain.operations import takes_cash
from app.services import cash, clients, operations
from app.services.operations import COMMENT_MAX

router = Router(name="operation_steps")


def _step(action: OpAction):
    return OpCb.filter(F.action == action)


async def _flow(event: Event, state: FSMContext, bot: Bot, user: User) -> Flow | None:
    """The scenario data, or None (and the menu) if it is gone, e.g. after a restart."""
    flow = await operation.load(state)
    if flow is None:
        if isinstance(event, CallbackQuery):
            await answer(event, texts.STALE_ACTION)
        await finish(bot, state, chat_id_of(event), user, texts.STALE_ACTION)
    return flow


# --- client (TZ 12.2) --------------------------------------------------------------------------


@router.callback_query(OperationFlow.client, _step(OpAction.CLIENT), OnScreen())
async def pick_client(
    callback: CallbackQuery,
    callback_data: OpCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    flow = await _flow(callback, state, bot, user)
    if flow is None:
        return
    try:
        client = await clients.get_client(session, int(callback_data.value))
    except errors.ClientNotFound:
        await answer(callback, texts.CLIENT_NOT_FOUND)
        await operation.show_client_step(callback, state, bot, session, flow)
        return
    flow.client_id, flow.client_name = client.id, client.name
    await operation.after_client(callback, state, bot, session, flow)
    await answer(callback)


@router.callback_query(OperationFlow.client, _step(OpAction.SEARCH), OnScreen())
async def ask_search(callback: CallbackQuery, state: FSMContext, bot: Bot, user: User) -> None:
    flow = await _flow(callback, state, bot, user)
    if flow is None:
        return
    await operation.show_search_prompt(callback, state, bot, flow)
    await answer(callback)


@router.message(OperationFlow.client, F.text)
async def search(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    # Text typed on the client step is a search query (TZ 12.2).
    assert message.text is not None
    flow = await _flow(message, state, bot, user)
    if flow is None:
        return
    query = clients.normalize_query(message.text)
    if not query:
        await operation.show_search_prompt(message, state, bot, flow)
        return
    flow.query = query
    await operation.show_search_results(message, state, bot, session, flow, 0)


@router.callback_query(OperationFlow.client, _step(OpAction.RESULTS), OnScreen())
async def results_page(
    callback: CallbackQuery,
    callback_data: OpCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    flow = await _flow(callback, state, bot, user)
    if flow is None:
        return
    if not flow.query:
        await answer(callback, texts.STALE_ACTION)
        return
    await operation.show_search_results(
        callback, state, bot, session, flow, int(callback_data.value)
    )
    await answer(callback)


@router.callback_query(OperationFlow.client, _step(OpAction.NEW_CLIENT), OnScreen())
async def new_client(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await operation.show_new_client_name(callback, state, bot)
    await answer(callback)


@router.message(OperationFlow.new_client_name, F.text)
async def new_client_name(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    try:
        name = await clients.check_name_available(session, message.text)
    except errors.InvalidClientName as error:
        text = texts.CLIENT_NAME_TOO_LONG if error.too_long else texts.CLIENT_NAME_EMPTY
        await operation.show_new_client_name(message, state, bot, text)
        return
    except errors.DuplicateClientName as error:
        await operation.show_new_client_name(
            message, state, bot, texts.duplicate_client(error.existing_name)
        )
        return
    await state.update_data(new_client_name=name)
    await operation.show_new_client_comment(message, state, bot)


async def _create_client(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    comment: str | None,
) -> None:
    flow = await _flow(event, state, bot, user)
    if flow is None or flow.new_client_name is None:
        return
    try:
        client = await clients.create_client(session, user, flow.new_client_name, comment)
    except errors.TextTooLong as error:
        await operation.show_new_client_comment(
            event, state, bot, texts.comment_too_long(error.limit)
        )
        return
    except errors.DuplicateClientName as error:
        await operation.show_new_client_name(
            event, state, bot, texts.duplicate_client(error.existing_name)
        )
        return
    flow.client_id, flow.client_name, flow.new_client_name = client.id, client.name, None
    await operation.after_client(event, state, bot, session, flow)


@router.message(OperationFlow.new_client_comment, F.text)
async def new_client_comment(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await _create_client(message, state, bot, session, user, message.text)


@router.callback_query(
    OperationFlow.new_client_comment, _step(OpAction.SKIP_CLIENT_COMMENT), OnScreen()
)
async def skip_client_comment(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await answer(callback)
    await _create_client(callback, state, bot, session, user, None)


# --- amount ------------------------------------------------------------------------------------


@router.message(OperationFlow.amount, F.text)
async def receive_amount(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    flow = await _flow(message, state, bot, user)
    if flow is None:
        return
    try:
        amount = parse_amount(message.text)
    except errors.InvalidNumber as error:
        problem = texts.AMOUNT_ERRORS[error.problem]
        await operation.show_amount(message, state, bot, session, flow, problem)
        return
    if takes_cash(flow.op_type):
        # Early, friendly check; the final one runs under a lock when saving (TZ 7.4).
        try:
            await cash.check_available(session, flow.cash_currency, amount)
        except errors.InsufficientCash as error:
            problem = texts.insufficient_cash_retry(error)
            await operation.show_amount(message, state, bot, session, flow, problem)
            return
    flow.amount = amount
    await operation.after_amount(message, state, bot, session, flow)


# --- date (TZ 7.6) -----------------------------------------------------------------------------


@router.callback_query(
    OperationFlow.date, OpCb.filter(F.action.in_({OpAction.TODAY, OpAction.YESTERDAY})), OnScreen()
)
async def quick_date(
    callback: CallbackQuery,
    callback_data: OpCb,
    state: FSMContext,
    bot: Bot,
    user: User,
    settings: Settings,
) -> None:
    flow = await _flow(callback, state, bot, user)
    if flow is None:
        return
    current = today(settings.zone)
    flow.op_date = current if callback_data.action == OpAction.TODAY else yesterday(current)
    await operation.store(state, flow)
    await operation.show_comment(callback, state, bot, flow)
    await answer(callback)


@router.callback_query(OperationFlow.date, _step(OpAction.OTHER_DATE), OnScreen())
async def ask_custom_date(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await operation.show_custom_date(callback, state, bot)
    await answer(callback)


@router.message(OperationFlow.custom_date, F.text)
async def receive_custom_date(
    message: Message, state: FSMContext, bot: Bot, user: User, settings: Settings
) -> None:
    assert message.text is not None
    flow = await _flow(message, state, bot, user)
    if flow is None:
        return
    try:
        flow.op_date = parse_date(message.text, today(settings.zone))
    except errors.FutureDate:
        await operation.show_custom_date(message, state, bot, texts.FUTURE_DATE)
        return
    except errors.InvalidDate:
        await operation.show_custom_date(message, state, bot, texts.INVALID_DATE)
        return
    await operation.store(state, flow)
    await operation.show_comment(message, state, bot, flow)


# --- comment and confirmation ------------------------------------------------------------------


async def _confirm(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User, flow: Flow
) -> None:
    await operation.store(state, flow)
    try:
        await operation.show_confirm(event, state, bot, session, flow)
    except errors.ClientNotFound:
        await finish(
            bot,
            state,
            chat_id_of(event),
            user,
            f"{texts.CLIENT_NOT_FOUND}\n{texts.RECORD_NOT_SAVED}",
        )


@router.message(OperationFlow.comment, F.text)
async def receive_comment(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    flow = await _flow(message, state, bot, user)
    if flow is None:
        return
    try:
        flow.comment = clients.normalize_comment(message.text, COMMENT_MAX)
    except errors.TextTooLong as error:
        await operation.show_comment(message, state, bot, flow, texts.comment_too_long(error.limit))
        return
    await _confirm(message, state, bot, session, user, flow)


@router.callback_query(OperationFlow.comment, _step(OpAction.SKIP_COMMENT), OnScreen())
async def skip_comment(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    flow = await _flow(callback, state, bot, user)
    if flow is None:
        return
    flow.comment = None
    await _confirm(callback, state, bot, session, user, flow)
    await answer(callback)


@router.callback_query(OperationFlow.confirm, _step(OpAction.SAVE), OnScreen())
async def save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    flow = await _flow(callback, state, bot, user)
    if flow is None:
        return
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        record, _created = await operations.create_operation(session, user, flow.draft())
    except errors.InsufficientCash as error:
        await finish(bot, state, chat_id, user, texts.insufficient_cash_not_saved(error))
        return
    except errors.ClientNotFound:
        await finish(
            bot, state, chat_id, user, f"{texts.CLIENT_NOT_FOUND}\n{texts.RECORD_NOT_SAVED}"
        )
        return
    await finish(
        bot, state, chat_id, user, texts.record_saved(record.id), kb.open_record(record.id)
    )


@router.callback_query(OperationFlow.confirm, _step(OpAction.DONT_SAVE), OnScreen())
async def dont_save(callback: CallbackQuery, state: FSMContext, bot: Bot, user: User) -> None:
    assert callback.message is not None
    await state.clear()
    await edit_or_send(bot, callback.message, texts.MAIN_MENU, main_menu(user))
    await answer(callback, texts.RECORD_NOT_SAVED)


# --- back --------------------------------------------------------------------------------------


@router.callback_query(StateFilter(OperationFlow), _step(OpAction.BACK), OnScreen())
async def back(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    flow = await _flow(callback, state, bot, user)
    if flow is None:
        return
    await operation.go_back(callback, state, bot, session, flow)
    await answer(callback)
