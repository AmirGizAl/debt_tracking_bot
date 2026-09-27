"""Clients section: list, search, add, card, edit, delete (TZ 10, 12.6)."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import ClientsAction, ClientsCb, MenuAction, MenuCb
from app.bot.keyboards import clients as kb
from app.bot.states import ClientsFlow
from app.bot.ui import (
    OnScreen,
    answer,
    chat_id_of,
    drop_keyboard,
    edit_or_send,
    finish,
    leave_scenario,
    show_step,
)
from app.db.models import Client, User
from app.services import balances, clients

router = Router(name="clients")


def _action(action: ClientsAction):
    return ClientsCb.filter(F.action == action)


async def _client_or_stale(
    callback: CallbackQuery, session: AsyncSession, client_id: int
) -> Client | None:
    try:
        return await clients.get_client(session, client_id)
    except clients.ClientNotFound:
        await answer(callback, texts.STALE_ACTION)
        return None


def _name_error(error: clients.InvalidClientName) -> str:
    return texts.CLIENT_NAME_TOO_LONG if error.too_long else texts.CLIENT_NAME_EMPTY


# --- list and card -----------------------------------------------------------------------------


async def _show_list(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, number: int
) -> None:
    await leave_scenario(callback, state, bot)
    page = await clients.list_clients(session, number)
    text = texts.CLIENTS_TITLE if page.total else f"{texts.CLIENTS_TITLE}\n{texts.CLIENTS_EMPTY}"
    await edit_or_send(bot, callback.message, text, kb.clients_list(page))
    await answer(callback)


@router.callback_query(MenuCb.filter(F.action == MenuAction.CLIENTS))
async def open_clients(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    await _show_list(callback, state, bot, session, 0)


@router.callback_query(_action(ClientsAction.LIST))
async def clients_page(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await _show_list(callback, state, bot, session, callback_data.page)


async def render_card(
    bot: Bot, callback: CallbackQuery, session: AsyncSession, client: Client
) -> None:
    client_balances = await balances.client_balances(session, client.id)
    can_delete = not await clients.has_operations(session, client.id)
    await edit_or_send(
        bot,
        callback.message,
        texts.client_card(client, client_balances),
        kb.client_card(client, can_delete),
    )


@router.callback_query(_action(ClientsAction.OPEN))
async def open_client(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    client = await _client_or_stale(callback, session, callback_data.client_id)
    if client is None:
        return
    await leave_scenario(callback, state, bot)
    await render_card(bot, callback, session, client)
    await answer(callback)


# --- search ------------------------------------------------------------------------------------


@router.callback_query(_action(ClientsAction.SEARCH))
async def ask_search(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await leave_scenario(callback, state, bot)
    await state.set_state(ClientsFlow.search)
    await show_step(callback, state, bot, texts.ASK_SEARCH, kb.back_to_list())
    await answer(callback)


@router.message(ClientsFlow.search, F.text)
async def run_search(message: Message, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    assert message.text is not None
    query = clients.normalize_query(message.text)
    if not query:
        await show_step(message, state, bot, texts.ASK_SEARCH, kb.back_to_list())
        return
    await state.update_data(query=query)
    page = await clients.search_clients(session, query, 0)
    await show_step(
        message, state, bot, texts.search_results(query, page.total), kb.search_results(page)
    )


@router.callback_query(ClientsFlow.search, _action(ClientsAction.RESULTS), OnScreen())
async def search_page(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    query = (await state.get_data())["query"]
    page = await clients.search_clients(session, query, callback_data.page)
    await show_step(
        callback, state, bot, texts.search_results(query, page.total), kb.search_results(page)
    )
    await answer(callback)


# --- add ---------------------------------------------------------------------------------------


@router.callback_query(_action(ClientsAction.ADD))
async def ask_name(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await leave_scenario(callback, state, bot)
    await state.set_state(ClientsFlow.add_name)
    await show_step(callback, state, bot, texts.ASK_CLIENT_NAME, kb.back_to_list())
    await answer(callback)


@router.callback_query(ClientsFlow.add_comment, _action(ClientsAction.BACK_TO_NAME), OnScreen())
async def back_to_name(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.set_state(ClientsFlow.add_name)
    await show_step(callback, state, bot, texts.ASK_CLIENT_NAME, kb.back_to_list())
    await answer(callback)


@router.message(ClientsFlow.add_name, F.text)
async def receive_name(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    assert message.text is not None
    try:
        name = await clients.check_name_available(session, message.text)
    except clients.InvalidClientName as error:
        await show_step(message, state, bot, _name_error(error), kb.back_to_list())
        return
    except clients.DuplicateClientName as error:
        await show_step(
            message, state, bot, texts.duplicate_client(error.existing_name), kb.back_to_list()
        )
        return
    await state.update_data(name=name)
    await state.set_state(ClientsFlow.add_comment)
    await show_step(message, state, bot, texts.ASK_CLIENT_COMMENT, kb.ask_comment())


async def _create_client(
    event: Message | CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    comment: str | None,
) -> None:
    chat_id = chat_id_of(event)
    name = (await state.get_data())["name"]
    try:
        client = await clients.create_client(session, user, name, comment)
    except clients.CommentTooLong as error:
        await show_step(event, state, bot, texts.comment_too_long(error.limit), kb.ask_comment())
        return
    except clients.DuplicateClientName as error:
        await state.set_state(ClientsFlow.add_name)
        await show_step(
            event, state, bot, texts.duplicate_client(error.existing_name), kb.back_to_list()
        )
        return
    await finish(
        bot, state, chat_id, user, texts.client_added(client.name), kb.open_client(client.id)
    )


@router.message(ClientsFlow.add_comment, F.text)
async def receive_comment(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await _create_client(message, state, bot, session, user, message.text)


@router.callback_query(ClientsFlow.add_comment, _action(ClientsAction.SKIP_COMMENT), OnScreen())
async def skip_comment(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await answer(callback)
    await _create_client(callback, state, bot, session, user, None)


# --- edit --------------------------------------------------------------------------------------


@router.callback_query(_action(ClientsAction.EDIT))
async def edit_menu(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    client = await _client_or_stale(callback, session, callback_data.client_id)
    if client is None:
        return
    await leave_scenario(callback, state, bot)
    await edit_or_send(
        bot, callback.message, texts.edit_client(client.name), kb.edit_menu(client.id)
    )
    await answer(callback)


@router.callback_query(_action(ClientsAction.EDIT_NAME))
async def ask_new_name(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    client = await _client_or_stale(callback, session, callback_data.client_id)
    if client is None:
        return
    await leave_scenario(callback, state, bot)
    await state.set_state(ClientsFlow.edit_name)
    await state.update_data(client_id=client.id)
    await show_step(
        callback, state, bot, texts.ask_new_name(client.name), kb.back_to_edit(client.id)
    )
    await answer(callback)


@router.message(ClientsFlow.edit_name, F.text)
async def receive_new_name(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    client_id = (await state.get_data())["client_id"]
    try:
        client = await clients.rename_client(session, client_id, message.text)
    except clients.InvalidClientName as error:
        await show_step(message, state, bot, _name_error(error), kb.back_to_edit(client_id))
        return
    except clients.DuplicateClientName as error:
        await show_step(
            message,
            state,
            bot,
            texts.duplicate_client(error.existing_name),
            kb.back_to_edit(client_id),
        )
        return
    except clients.ClientNotFound:
        await finish(bot, state, message.chat.id, user, texts.CLIENT_NOT_FOUND)
        return
    await finish(
        bot,
        state,
        message.chat.id,
        user,
        texts.client_renamed(client.name),
        kb.open_client(client.id),
    )


@router.callback_query(_action(ClientsAction.EDIT_COMMENT))
async def ask_new_comment(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    client = await _client_or_stale(callback, session, callback_data.client_id)
    if client is None:
        return
    await leave_scenario(callback, state, bot)
    await state.set_state(ClientsFlow.edit_comment)
    await state.update_data(client_id=client.id)
    await show_step(
        callback,
        state,
        bot,
        texts.ask_new_comment(client.comment),
        kb.edit_comment(client.id, has_comment=client.comment is not None),
    )
    await answer(callback)


async def _save_comment(
    chat_id: int,
    event: Message | CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    comment: str | None,
) -> None:
    client_id = (await state.get_data())["client_id"]
    try:
        client = await clients.update_comment(session, client_id, comment)
    except clients.CommentTooLong as error:
        await show_step(
            event, state, bot, texts.comment_too_long(error.limit), kb.edit_comment(client_id, True)
        )
        return
    except clients.ClientNotFound:
        await finish(bot, state, chat_id, user, texts.CLIENT_NOT_FOUND)
        return
    result = texts.COMMENT_SAVED if client.comment else texts.COMMENT_REMOVED
    await finish(bot, state, chat_id, user, result, kb.open_client(client.id))


@router.message(ClientsFlow.edit_comment, F.text)
async def receive_new_comment(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await _save_comment(message.chat.id, message, state, bot, session, user, message.text)


@router.callback_query(ClientsFlow.edit_comment, _action(ClientsAction.CLEAR_COMMENT), OnScreen())
async def clear_comment(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await answer(callback)
    await _save_comment(chat_id_of(callback), callback, state, bot, session, user, None)


# --- delete ------------------------------------------------------------------------------------


@router.callback_query(_action(ClientsAction.DELETE))
async def confirm_delete(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    client = await _client_or_stale(callback, session, callback_data.client_id)
    if client is None:
        return
    if await clients.has_operations(session, client.id):
        await answer(callback, texts.CLIENT_HAS_OPERATIONS, alert=True)
        return
    await leave_scenario(callback, state, bot)
    await edit_or_send(
        bot,
        callback.message,
        texts.confirm_delete_client(client.name),
        kb.confirm_delete(client.id),
    )
    await answer(callback)


@router.callback_query(_action(ClientsAction.CONFIRM_DELETE))
async def delete_client(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    assert callback.message is not None
    try:
        client = await clients.delete_client(session, callback_data.client_id)
    except clients.ClientNotFound:
        await answer(callback, texts.STALE_ACTION)
        return
    except clients.ClientHasOperations:
        await answer(callback, texts.CLIENT_HAS_OPERATIONS, alert=True)
        return
    await answer(callback)
    await drop_keyboard(bot, callback.message.chat.id, callback.message.message_id)
    await finish(bot, state, callback.message.chat.id, user, texts.client_deleted(client.name))


# --- not built yet -----------------------------------------------------------------------------


@router.callback_query(
    ClientsCb.filter(F.action.in_({ClientsAction.HISTORY, ClientsAction.STATEMENT}))
)
async def not_implemented(callback: CallbackQuery) -> None:
    await answer(callback, texts.NOT_IMPLEMENTED)
