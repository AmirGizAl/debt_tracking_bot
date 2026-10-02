"""Settings (owner only): helpers list, invitation, card, deletion (TZ 9, 12.9)."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb, SettingsAction, SettingsCb
from app.bot.keyboards import settings as kb
from app.bot.notify import notify_group
from app.bot.states import HelperFlow
from app.bot.ui import (
    answer,
    drop_keyboard,
    edit_or_send,
    finish,
    leave_any,
    leave_scenario,
    show_screen,
    show_step,
)
from app.config import Settings
from app.db.models import User
from app.domain import errors
from app.services import users

router = Router(name="settings")


async def _owner_only(callback: CallbackQuery, user: User) -> bool:
    if user.is_owner and callback.message is not None:
        return True
    await answer(callback, texts.PERMISSION_DENIED, alert=True)
    return False


async def show_settings(event: Message | CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Owner only: callers check the role first."""
    await leave_any(event, state, bot)
    await show_screen(event, bot, texts.SETTINGS_TITLE, kb.settings_menu())


@router.callback_query(MenuCb.filter(F.action == MenuAction.SETTINGS))
@router.callback_query(SettingsCb.filter(F.action == SettingsAction.HOME))
async def open_settings(callback: CallbackQuery, state: FSMContext, bot: Bot, user: User) -> None:
    if not await _owner_only(callback, user):
        return
    await show_settings(callback, state, bot)
    await answer(callback)


@router.callback_query(SettingsCb.filter(F.action == SettingsAction.HELPERS))
async def show_helpers(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if not await _owner_only(callback, user):
        return
    await leave_scenario(callback, state, bot)
    helpers = await users.list_helpers(session, user)
    text = texts.HELPERS_TITLE if helpers else f"{texts.HELPERS_TITLE}\n{texts.HELPERS_EMPTY}"
    await edit_or_send(bot, callback.message, text, kb.helpers_list(helpers))
    await answer(callback)


@router.callback_query(SettingsCb.filter(F.action == SettingsAction.ADD))
async def ask_username(callback: CallbackQuery, state: FSMContext, bot: Bot, user: User) -> None:
    if not await _owner_only(callback, user):
        return
    await leave_scenario(callback, state, bot)
    await state.set_state(HelperFlow.username)
    await show_step(callback, state, bot, texts.ASK_HELPER_USERNAME, kb.ask_username())
    await answer(callback)


@router.message(HelperFlow.username, F.text)
async def receive_username(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    try:
        helper = await users.add_helper(session, user, message.text)
    except errors.InvalidUsername:
        await show_step(message, state, bot, texts.INVALID_USERNAME, kb.ask_username())
        return
    except errors.UsernameAlreadyAdded:
        await show_step(message, state, bot, texts.USERNAME_ALREADY_ADDED, kb.ask_username())
        return
    assert helper.username is not None
    await finish(bot, state, message.chat.id, user, session, texts.helper_added(helper.username))


@router.callback_query(SettingsCb.filter(F.action == SettingsAction.OPEN))
async def open_helper(
    callback: CallbackQuery,
    callback_data: SettingsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    if not await _owner_only(callback, user):
        return
    try:
        helper = await users.get_helper(session, user, callback_data.helper_id)
    except errors.UserNotFound:
        await answer(callback, texts.STALE_ACTION)
        return
    await leave_scenario(callback, state, bot)
    added_on = helper.created_at.astimezone(settings.zone).date()
    await edit_or_send(
        bot, callback.message, texts.helper_card(helper, added_on), kb.helper_card(helper)
    )
    await answer(callback)


@router.callback_query(SettingsCb.filter(F.action == SettingsAction.DELETE))
async def ask_delete_confirmation(
    callback: CallbackQuery,
    callback_data: SettingsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    if not await _owner_only(callback, user):
        return
    try:
        helper = await users.get_helper(session, user, callback_data.helper_id)
    except errors.UserNotFound:
        await answer(callback, texts.STALE_ACTION)
        return
    await leave_scenario(callback, state, bot)
    await edit_or_send(
        bot, callback.message, texts.confirm_delete_helper(helper), kb.confirm_delete(helper)
    )
    await answer(callback)


@router.callback_query(SettingsCb.filter(F.action == SettingsAction.CONFIRM_DELETE))
async def delete_helper(
    callback: CallbackQuery,
    callback_data: SettingsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    if not await _owner_only(callback, user):
        return
    assert callback.message is not None
    try:
        helper = await users.delete_helper(session, user, callback_data.helper_id)
    except errors.UserNotFound:
        await answer(callback, texts.STALE_ACTION)
        return
    except errors.CannotDeleteOwner:
        await answer(callback, texts.CANNOT_DELETE_OWNER, alert=True)
        return
    if helper.telegram_id is not None:
        # Whatever the helper was doing is dropped with the access (TZ 9.4).
        key = StorageKey(bot_id=bot.id, chat_id=helper.telegram_id, user_id=helper.telegram_id)
        await state.storage.set_state(key, None)
        await state.storage.set_data(key, {})
    await answer(callback)
    await drop_keyboard(bot, callback.message.chat.id, callback.message.message_id)
    await finish(bot, state, callback.message.chat.id, user, session, texts.helper_deleted(helper))
    await notify_group(bot, settings, texts.helper_deleted(helper))
