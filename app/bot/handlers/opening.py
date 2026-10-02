"""«Начальные балансы» in the settings (TZ 9, 13.11). Owners only.

While day №1 is open: currency -> amount -> confirmation; one record per currency that is
not cancelled. After the first closing the screen only shows the values.
"""

import uuid
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import OpeningAction, OpeningCb
from app.bot.keyboards import opening as kb
from app.bot.keyboards.common import main_menu
from app.bot.states import OpeningFlow
from app.bot.ui import (
    OnScreen,
    answer,
    chat_id_of,
    edit_or_send,
    finish,
    leave_scenario,
    menu_text,
    show_step,
)
from app.db.models import User
from app.domain import errors
from app.domain.currency import CURRENCIES, Currency
from app.domain.money import parse_amount
from app.services import ledger, opening

router = Router(name="opening")

Event = Message | CallbackQuery


def _step(action: OpeningAction):
    return OpeningCb.filter(F.action == action)


async def _owner_only(callback: CallbackQuery, user: User) -> bool:
    if user.is_owner and callback.message is not None:
        return True
    await answer(callback, texts.PERMISSION_DENIED, alert=True)
    return False


async def _free_currencies(session: AsyncSession) -> list[Currency]:
    """Currencies without an opening record that is not cancelled (02.10.2026)."""
    return [c for c in CURRENCIES if await opening.active_opening(session, c) is None]


async def show_opening(callback: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    assert callback.message is not None
    frozen = await opening.baseline_frozen(session)
    free = await _free_currencies(session)
    text = texts.opening_screen(await opening.baseline(session), frozen, all_entered=not free)
    await edit_or_send(bot, callback.message, text, kb.screen(can_enter=not frozen and bool(free)))


@router.callback_query(_step(OpeningAction.SHOW))
async def open_screen(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if not await _owner_only(callback, user):
        return
    await leave_scenario(callback, state, bot)
    await show_opening(callback, bot, session)
    await answer(callback)


async def _show_currencies(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    await state.set_state(OpeningFlow.currency)
    text = f"{texts.OPENING_TITLE}\n\n<b>{texts.ASK_OPENING_CURRENCY}</b>"
    await show_step(event, state, bot, text, kb.currencies(await _free_currencies(session)))


async def _show_amount(
    event: Event, state: FSMContext, bot: Bot, currency: Currency, problem: str | None = None
) -> None:
    text = texts.ask_opening_amount(currency)
    if problem:
        text = f"{text}\n\n{problem}"
    await state.set_state(OpeningFlow.amount)
    await show_step(event, state, bot, text, kb.back_only())


async def _show_confirm(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    currency: Currency,
    amount: Decimal,
) -> None:
    balance = await ledger.balance(session, currency)
    await state.set_state(OpeningFlow.confirm)
    text = texts.confirm_opening(currency, amount, balance + amount)
    await show_step(event, state, bot, text, kb.confirm())


@router.callback_query(_step(OpeningAction.ENTER))
async def enter(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    if not await _owner_only(callback, user):
        return
    if await opening.baseline_frozen(session):
        await answer(callback, texts.OPENING_FROZEN, alert=True)
        await show_opening(callback, bot, session)
        return
    await leave_scenario(callback, state, bot)
    await state.set_data({"request_id": str(uuid.uuid4())})
    await _show_currencies(callback, state, bot, session)
    await answer(callback)


@router.callback_query(OpeningFlow.currency, _step(OpeningAction.CURRENCY), OnScreen())
async def choose_currency(
    callback: CallbackQuery, callback_data: OpeningCb, state: FSMContext, bot: Bot
) -> None:
    currency = Currency(callback_data.value)
    await state.update_data(currency=str(currency), amount=None)
    await _show_amount(callback, state, bot, currency)
    await answer(callback)


@router.message(OpeningFlow.amount, F.text)
async def receive_amount(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    assert message.text is not None
    currency = Currency((await state.get_data())["currency"])
    try:
        amount = parse_amount(message.text)
    except errors.InvalidNumber as error:
        await _show_amount(message, state, bot, currency, texts.AMOUNT_ERRORS[error.problem])
        return
    await state.update_data(amount=str(amount))
    await _show_confirm(message, state, bot, session, currency, amount)


@router.callback_query(OpeningFlow.confirm, _step(OpeningAction.SAVE), OnScreen())
async def save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await answer(callback)
    data = await state.get_data()
    currency, chat_id = Currency(data["currency"]), chat_id_of(callback)
    try:
        record, _created = await opening.create_opening(
            session, user, uuid.UUID(data["request_id"]), currency, Decimal(data["amount"])
        )
    except errors.OpeningExists:
        text = f"{texts.opening_exists(currency)}\n{texts.RECORD_NOT_SAVED}"
        await finish(bot, state, chat_id, user, session, text)
        return
    except errors.BaselineFrozen:
        text = f"{texts.OPENING_FROZEN}\n{texts.RECORD_NOT_SAVED}"
        await finish(bot, state, chat_id, user, session, text)
        return
    await finish(bot, state, chat_id, user, session, texts.record_saved(record.id))


@router.callback_query(OpeningFlow.confirm, _step(OpeningAction.DONT_SAVE), OnScreen())
async def dont_save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert callback.message is not None
    await state.clear()
    await edit_or_send(bot, callback.message, await menu_text(session), main_menu(user))
    await answer(callback, texts.RECORD_NOT_SAVED)


@router.callback_query(StateFilter(OpeningFlow), _step(OpeningAction.BACK), OnScreen())
async def back(callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    current = await state.get_state()
    data = await state.get_data()
    if current == OpeningFlow.currency.state:
        await leave_scenario(callback, state, bot)
        await show_opening(callback, bot, session)
    elif current == OpeningFlow.amount.state:
        await _show_currencies(callback, state, bot, session)
    else:
        await _show_amount(callback, state, bot, Currency(data["currency"]))
    await answer(callback)
