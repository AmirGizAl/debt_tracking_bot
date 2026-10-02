"""Handlers of the client picker shared by scenarios (see app/bot/flows/client_picker.py)."""

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import PickAction, PickCb
from app.bot.flows import client_picker as picker
from app.bot.states import ClientPick
from app.bot.ui import OnScreen, answer, chat_id_of, finish
from app.db.models import User
from app.domain import errors
from app.services import clients

router = Router(name="client_picker")

Event = Message | CallbackQuery


def _step(action: PickAction):
    return PickCb.filter(F.action == action)


async def _target(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> picker.Target | None:
    """The scenario that asked for a client, or None (and the menu) if it is gone."""
    target = picker.target_of(await state.get_data())
    if target is None:
        if isinstance(event, CallbackQuery):
            await answer(event, texts.STALE_ACTION)
        await finish(bot, state, chat_id_of(event), user, session, texts.STALE_ACTION)
    return target


@router.callback_query(ClientPick.choose, _step(PickAction.CLIENT), OnScreen())
async def pick(
    callback: CallbackQuery,
    callback_data: PickCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    target = await _target(callback, state, bot, session, user)
    if target is None:
        return
    try:
        client = await clients.get_client(session, int(callback_data.value))
    except errors.ClientNotFound:
        await answer(callback, texts.CLIENT_NOT_FOUND)
        await picker.show_choose(callback, state, bot, session)
        return
    await target.on_picked(callback, state, bot, session, user, client)
    await answer(callback)


@router.callback_query(ClientPick.choose, _step(PickAction.SEARCH), OnScreen())
async def ask_search(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await picker.show_search_prompt(callback, state, bot)
    await answer(callback)


@router.message(ClientPick.choose, F.text)
async def search(message: Message, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    # Text typed on the client step is a search query (TZ 13.3 step 6).
    assert message.text is not None
    query = clients.normalize_query(message.text)
    if not query:
        await picker.show_search_prompt(message, state, bot)
        return
    await picker.show_results(message, state, bot, session, query, 0)


@router.callback_query(ClientPick.choose, _step(PickAction.RESULTS), OnScreen())
async def results_page(
    callback: CallbackQuery,
    callback_data: PickCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    query = (await state.get_data()).get(picker.QUERY_KEY)
    if not query:
        await answer(callback, texts.STALE_ACTION)
        return
    await picker.show_results(callback, state, bot, session, query, int(callback_data.value))
    await answer(callback)


@router.callback_query(ClientPick.choose, _step(PickAction.NEW), OnScreen())
async def new_client(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    target = await _target(callback, state, bot, session, user)
    if target is None:
        return
    if not target.allow_new:
        await answer(callback, texts.STALE_ACTION)
        return
    await picker.show_new_name(callback, state, bot)
    await answer(callback)


@router.message(ClientPick.new_name, F.text)
async def new_client_name(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    assert message.text is not None
    try:
        name = await clients.check_name_available(session, message.text)
    except errors.InvalidClientName as error:
        text = texts.CLIENT_NAME_TOO_LONG if error.too_long else texts.CLIENT_NAME_EMPTY
        await picker.show_new_name(message, state, bot, text)
        return
    except errors.DuplicateClientName as error:
        await picker.show_new_name(message, state, bot, texts.duplicate_client(error.existing_name))
        return
    await state.update_data({picker.NEW_NAME_KEY: name})
    await picker.show_new_comment(message, state, bot)


async def _create_client(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    comment: str | None,
) -> None:
    target = await _target(event, state, bot, session, user)
    name = (await state.get_data()).get(picker.NEW_NAME_KEY)
    if target is None or name is None:
        return
    try:
        client = await clients.create_client(session, user, name, comment)
    except errors.TextTooLong as error:
        await picker.show_new_comment(event, state, bot, texts.comment_too_long(error.limit))
        return
    except errors.DuplicateClientName as error:
        await picker.show_new_name(event, state, bot, texts.duplicate_client(error.existing_name))
        return
    await state.update_data({picker.NEW_NAME_KEY: None})
    await target.on_picked(event, state, bot, session, user, client)


@router.message(ClientPick.new_comment, F.text)
async def new_client_comment(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await _create_client(message, state, bot, session, user, message.text)


@router.callback_query(ClientPick.new_comment, _step(PickAction.SKIP_COMMENT), OnScreen())
async def skip_client_comment(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await answer(callback)
    await _create_client(callback, state, bot, session, user, None)


@router.callback_query(StateFilter(ClientPick), _step(PickAction.BACK), OnScreen())
async def back(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if await _target(callback, state, bot, session, user) is None:
        return
    await picker.go_back(callback, state, bot, session, user)
    await answer(callback)
