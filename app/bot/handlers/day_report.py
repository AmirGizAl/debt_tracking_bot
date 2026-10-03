"""The preliminary report and the closing of the day (TZ 7.2, 8.2, 8.3, 13.9).

rates (TZ 8.2, «Как в прошлый раз») -> the numbers of the report, then
- the preliminary report: «Excel» or «PDF», a file; nothing is saved;
- the closing (owners): «Закрыть день №N» -> the snapshot, the files to every owner, the
  next day.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import DayAction, DayCb, MenuAction, MenuCb, ReportsAction, ReportsCb
from app.bot.flows import records
from app.bot.flows.records import Event, StoredForm
from app.bot.handlers.reports import show_reports
from app.bot.keyboards import day_report as kb
from app.bot.keyboards.common import main_menu
from app.bot.notify import notify_group, send_day_report
from app.bot.states import DayReportFlow
from app.bot.ui import (
    OnScreen,
    answer,
    chat_id_of,
    edit_or_send,
    finish,
    leave_any,
    menu_text,
    reset_scenario,
    send_menu,
    show_step,
)
from app.config import Settings
from app.db.models import User
from app.domain import errors
from app.domain.currency import Currency
from app.domain.money import parse_rate
from app.services import days, reports

logger = logging.getLogger(__name__)

router = Router(name="day_report")


class Purpose(StrEnum):
    PRELIMINARY = "pre"
    CLOSING = "close"


@dataclass
class Form(StoredForm):
    purpose: Purpose
    day_id: int
    currencies: list[str]  # the rates to ask, in the display order (TZ 8.2)
    rates: dict[str, str] = field(default_factory=dict)

    @property
    def closing(self) -> bool:
        return self.purpose == Purpose.CLOSING

    @property
    def title(self) -> str:
        if self.closing:
            return texts.closing_title(self.day_id)
        return texts.preliminary_step_title(self.day_id)

    def pending(self) -> Currency | None:
        """The first currency still without a rate."""
        for code in self.currencies:
            if code not in self.rates:
                return Currency(code)
        return None

    def decimal_rates(self) -> dict[Currency, Decimal]:
        return {Currency(code): Decimal(value) for code, value in self.rates.items()}


def _step(action: DayAction):
    return DayCb.filter(F.action == action)


async def _form(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> Form | None:
    return await records.current_form(Form, event, state, bot, session, user)


async def _store(state: FSMContext, form: Form) -> None:
    await state.update_data(form.dump())


# --- steps ---------------------------------------------------------------------------------------


async def show_rate(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    form: Form,
    problem: str | None = None,
) -> None:
    currency = form.pending()
    assert currency is not None
    previous = (await days.last_rates(session)).get(currency)
    entered = texts.rates_entered(form.decimal_rates())
    lines = [entered] if entered else []
    text = texts.step_text(form.title, lines, texts.ask_report_rate(currency), problem)
    label = texts.btn_previous_rate(previous) if previous is not None else None
    await state.set_state(DayReportFlow.rate)
    await show_step(event, state, bot, text, kb.rate_step(label))


async def _ask_new_rates(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, form: Form
) -> None:
    """Records in another currency came while the rates were typed: ask for those rates."""
    form.currencies = [str(currency) for currency in await days.rates_to_ask(session)]
    await _store(state, form)
    await show_rate(event, state, bot, session, form, texts.NEW_RATES_NEEDED)


async def show_check(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    form: Form,
) -> None:
    """The numbers of the report: the check before closing, or the preliminary report."""
    try:
        day, report = await days.preliminary_report(session, form.decimal_rates())
    except errors.MissingRate:
        await _ask_new_rates(event, state, bot, session, form)
        return
    if day.id != form.day_id:
        if form.closing:  # another owner has closed it meanwhile
            text = texts.day_already_closed(form.day_id)
            await finish(bot, state, chat_id_of(event), user, session, text)
            return
        form.day_id = day.id
        await _store(state, form)
    with_rates = bool(form.currencies)
    if form.closing:
        text = texts.day_check(texts.check_title(day.id), report)
        markup = kb.closing(day.id, with_rates)
    else:
        title = texts.preliminary_title(day.id, datetime.now(settings.zone))
        text = f"{texts.day_check(title, report)}\n\n{texts.CHOOSE_FORMAT}"
        markup = kb.preliminary(with_rates)
    await state.set_state(DayReportFlow.check)
    await show_step(event, state, bot, text, markup)


async def advance(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    form: Form,
) -> None:
    """The next rate, or the numbers when every rate is known."""
    if form.pending() is not None:
        await show_rate(event, state, bot, session, form)
    else:
        await show_check(event, state, bot, session, user, settings, form)


async def begin(
    event: Event,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    purpose: Purpose,
) -> None:
    await leave_any(event, state, bot)
    day = await days.ensure_open_day(session)
    currencies = [str(currency) for currency in await days.rates_to_ask(session)]
    form = Form(purpose=purpose, day_id=day.id, currencies=currencies)
    await state.set_data(form.dump())
    await advance(event, state, bot, session, user, settings, form)


# --- entry points --------------------------------------------------------------------------------


@router.callback_query(MenuCb.filter(F.action == MenuAction.CLOSE_DAY))
async def start_closing(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    if not user.is_owner:
        await answer(callback, texts.PERMISSION_DENIED, alert=True)
        return
    await begin(callback, state, bot, session, user, settings, Purpose.CLOSING)
    await answer(callback)


@router.callback_query(ReportsCb.filter(F.action == ReportsAction.PRELIMINARY))
async def start_preliminary(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    await begin(callback, state, bot, session, user, settings, Purpose.PRELIMINARY)
    await answer(callback)


# --- rates ---------------------------------------------------------------------------------------


@router.message(DayReportFlow.rate, F.text)
async def receive_rate(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    assert message.text is not None
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    currency = form.pending()
    if currency is None:
        await advance(message, state, bot, session, user, settings, form)
        return
    try:
        rate = parse_rate(message.text)
    except errors.InvalidNumber as error:
        await show_rate(message, state, bot, session, form, texts.RATE_ERRORS[error.problem])
        return
    form.rates[str(currency)] = str(rate)
    await _store(state, form)
    await advance(message, state, bot, session, user, settings, form)


@router.callback_query(DayReportFlow.rate, _step(DayAction.LAST_RATE), OnScreen())
async def previous_rate(
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
    currency = form.pending()
    previous = (await days.last_rates(session)).get(currency) if currency else None
    if currency is None or previous is None:
        await answer(callback, texts.STALE_ACTION)
        return
    form.rates[str(currency)] = str(previous)
    await _store(state, form)
    await advance(callback, state, bot, session, user, settings, form)
    await answer(callback)


@router.callback_query(DayReportFlow.check, _step(DayAction.CHANGE_RATES), OnScreen())
async def change_rates(
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
    form.rates = {}
    await _store(state, form)
    await advance(callback, state, bot, session, user, settings, form)
    await answer(callback)


# --- the preliminary report ----------------------------------------------------------------------


@router.callback_query(DayReportFlow.check, _step(DayAction.FILE), OnScreen())
async def preliminary_file(
    callback: CallbackQuery,
    callback_data: DayCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    if form.closing or callback_data.fmt is None:
        await answer(callback, texts.STALE_ACTION)
        return
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        async with ChatActionSender.upload_document(bot=bot, chat_id=chat_id):
            report = await reports.preliminary_file(
                session,
                form.decimal_rates(),
                callback_data.fmt,
                generated_by=texts.user_name(user),
                generated_at=datetime.now(settings.zone),
                zone=settings.zone,
            )
    except errors.MissingRate:
        await _ask_new_rates(callback, state, bot, session, form)
        return
    # The screen stays: the other format is one tap away.
    await bot.send_document(chat_id, BufferedInputFile(report.content, report.filename))


# --- the closing ---------------------------------------------------------------------------------


@router.callback_query(DayReportFlow.check, _step(DayAction.CLOSE), OnScreen())
async def close(
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
    if not form.closing:
        await answer(callback, texts.STALE_ACTION)
        return
    await answer(callback)
    chat_id = chat_id_of(callback)
    try:
        closed = await days.close_day(session, user, form.day_id, form.decimal_rates())
    except errors.DayAlreadyClosed:
        await finish(bot, state, chat_id, user, session, texts.day_already_closed(form.day_id))
        return
    except errors.MissingRate:
        await _ask_new_rates(callback, state, bot, session, form)
        return
    except errors.PermissionDenied:
        await finish(bot, state, chat_id, user, session, texts.PERMISSION_DENIED)
        return
    surplus = closed.report.surplus
    await bot.send_message(chat_id, texts.day_closed(closed.day.id, surplus, closed.next_day_id))
    await reset_scenario(state, bot, chat_id)
    async with ChatActionSender.upload_document(bot=bot, chat_id=chat_id):
        await send_day_report(bot, session, settings, closed, user)
    await send_menu(bot, chat_id, user, session)
    notice = texts.day_closed_notice(closed.day.id, surplus, closed.next_day_id, user)
    await notify_group(bot, settings, notice)
    logger.info("Day %s closed by user %s, surplus %s", closed.day.id, user.id, surplus)


@router.callback_query(DayReportFlow.check, _step(DayAction.DONT_CLOSE), OnScreen())
async def dont_close(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await state.clear()
    if callback.message is not None:
        await edit_or_send(bot, callback.message, await menu_text(session), main_menu(user))
    await answer(callback, texts.DAY_NOT_CLOSED)


# --- back ----------------------------------------------------------------------------------------


@router.callback_query(StateFilter(DayReportFlow), _step(DayAction.BACK), OnScreen())
async def back(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    pending = form.pending()
    position = form.currencies.index(pending) if pending is not None else len(form.currencies)
    if position > 0:  # back to the rate before the current step
        del form.rates[form.currencies[position - 1]]
        await _store(state, form)
        await show_rate(callback, state, bot, session, form)
    elif form.closing:
        await state.clear()
        if callback.message is not None:
            await edit_or_send(bot, callback.message, await menu_text(session), main_menu(user))
    else:
        await show_reports(callback, state, bot)
    await answer(callback)
