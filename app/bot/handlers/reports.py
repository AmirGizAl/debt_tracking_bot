"""Reports (TZ 12.8): choose a report, rates / client / period, format -> a file."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import ClientsAction, ClientsCb, MenuAction, MenuCb, RepAction, RepCb
from app.bot.handlers.clients import render_card
from app.bot.keyboards import reports as kb
from app.bot.keyboards.common import main_menu
from app.bot.states import ReportFlow
from app.bot.ui import (
    OnScreen,
    answer,
    chat_id_of,
    edit_or_send,
    leave_scenario,
    reset_scenario,
    show_step,
)
from app.config import Settings
from app.db.models import User
from app.domain import errors
from app.domain.currency import Currency
from app.domain.dates import month_bounds, parse_date, previous_month_bounds, today, year_start
from app.domain.money import parse_rate
from app.services import cash, clients, reports
from app.services.reports import PERIOD_KINDS, ReportFormat, ReportKind
from app.services.reports.data import Period, currencies_needing_rates

router = Router(name="reports")

Event = Message | CallbackQuery


def _step(action: RepAction):
    return RepCb.filter(F.action == action)


def _title(data: dict[str, Any]) -> str:
    return texts.REPORT_TITLES[data["kind"]]


# --- screens -----------------------------------------------------------------------------------


async def _show_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await leave_scenario(callback, state, bot)
    await edit_or_send(bot, callback.message, texts.REPORTS_TITLE, kb.report_menu())


async def _ask_next_rate(
    event: Event, state: FSMContext, bot: Bot, problem: str | None = None
) -> None:
    pending = (await state.get_data())["pending"]
    text = texts.ask_rate_for_summary(Currency(pending[0]))
    if problem:
        text = f"{problem}\n\n{text}"
    await state.set_state(ReportFlow.rates)
    await show_step(event, state, bot, text, kb.back_only())


async def _show_client_step(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    await state.update_data(query=None)
    recent = await clients.recent_clients(session)
    hint = texts.CHOOSE_CLIENT_HINT if recent else texts.STATEMENT_NO_CLIENTS
    await state.set_state(ReportFlow.client)
    await show_step(
        event,
        state,
        bot,
        f"<b>{texts.STATEMENT_CLIENT_QUESTION}</b>\n{hint}",
        kb.client_step(recent),
    )


async def _show_results(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, query: str, number: int
) -> None:
    await state.update_data(query=query)
    page = await clients.search_clients(session, query, number)
    await state.set_state(ReportFlow.client)
    await show_step(
        event, state, bot, texts.search_results(query, page.total), kb.search_results(page)
    )


async def _show_period(event: Event, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    question = texts.ASK_PERIOD
    if data.get("client_name"):
        question = f"Клиент: {texts.esc(data['client_name'])}\n{question}"
    await state.set_state(ReportFlow.period)
    await show_step(event, state, bot, texts.report_step(_title(data), question), kb.periods())


async def _ask_period_date(
    event: Event, state: FSMContext, bot: Bot, target: ReportFlow | Any, text: str
) -> None:
    await state.set_state(target)
    await show_step(event, state, bot, text, kb.back_only())


async def _show_format(event: Event, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.set_state(ReportFlow.format)
    await show_step(
        event, state, bot, texts.report_step(_title(data), texts.ASK_FORMAT), kb.formats()
    )


async def _start(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, kind: ReportKind
) -> None:
    await state.set_data({"kind": str(kind)})
    if kind == ReportKind.SUMMARY:
        pending = currencies_needing_rates(await cash.cash_balances(session))
        if pending:
            await state.update_data(pending=[str(c) for c in pending], rates={})
            await _ask_next_rate(event, state, bot)
            return
        await state.update_data(pending=[], rates={})
        await _show_format(event, state, bot)
    elif kind == ReportKind.DEBTS:
        await _show_format(event, state, bot)
    elif kind == ReportKind.STATEMENT:
        await _show_client_step(event, state, bot, session)
    else:
        await _show_period(event, state, bot)


# --- entry points ------------------------------------------------------------------------------


@router.callback_query(MenuCb.filter(F.action == MenuAction.REPORTS))
async def open_reports(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await _show_menu(callback, state, bot)
    await answer(callback)


@router.callback_query(_step(RepAction.KIND))
async def choose_report(
    callback: CallbackQuery,
    callback_data: RepCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    await leave_scenario(callback, state, bot)
    await _start(callback, state, bot, session, ReportKind(callback_data.value))
    await answer(callback)


@router.callback_query(ClientsCb.filter(F.action == ClientsAction.STATEMENT))
async def statement_from_card(
    callback: CallbackQuery,
    callback_data: ClientsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    try:
        client = await clients.get_client(session, callback_data.client_id)
    except errors.ClientNotFound:
        await answer(callback, texts.STALE_ACTION)
        return
    await leave_scenario(callback, state, bot)
    await state.set_data(
        {
            "kind": str(ReportKind.STATEMENT),
            "client_id": client.id,
            "client_name": client.name,
            "from_card": True,
        }
    )
    await _show_period(callback, state, bot)
    await answer(callback)


# --- rates for the summary (TZ 12.8) -----------------------------------------------------------


@router.message(ReportFlow.rates, F.text)
async def receive_rate(message: Message, state: FSMContext, bot: Bot) -> None:
    assert message.text is not None
    try:
        rate = parse_rate(message.text)
    except errors.InvalidNumber as error:
        await _ask_next_rate(message, state, bot, texts.RATE_ERRORS[error.problem])
        return
    data = await state.get_data()
    pending, rates = list(data["pending"]), dict(data["rates"])
    rates[pending.pop(0)] = str(rate)
    await state.update_data(pending=pending, rates=rates)
    if pending:
        await _ask_next_rate(message, state, bot)
    else:
        await _show_format(message, state, bot)


# --- client for the statement ------------------------------------------------------------------


@router.callback_query(ReportFlow.client, _step(RepAction.CLIENT), OnScreen())
async def pick_client(
    callback: CallbackQuery,
    callback_data: RepCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    try:
        client = await clients.get_client(session, int(callback_data.value))
    except errors.ClientNotFound:
        await answer(callback, texts.CLIENT_NOT_FOUND)
        return
    await state.update_data(client_id=client.id, client_name=client.name, from_card=False)
    await _show_period(callback, state, bot)
    await answer(callback)


@router.callback_query(ReportFlow.client, _step(RepAction.SEARCH), OnScreen())
async def ask_search(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.update_data(query="")
    await show_step(callback, state, bot, texts.ASK_SEARCH, kb.back_only())
    await answer(callback)


@router.message(ReportFlow.client, F.text)
async def search(message: Message, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    assert message.text is not None
    query = clients.normalize_query(message.text)
    if not query:
        await show_step(message, state, bot, texts.ASK_SEARCH, kb.back_only())
        return
    await _show_results(message, state, bot, session, query, 0)


@router.callback_query(ReportFlow.client, _step(RepAction.RESULTS), OnScreen())
async def results_page(
    callback: CallbackQuery,
    callback_data: RepCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
) -> None:
    query = (await state.get_data()).get("query")
    if not query:
        await answer(callback, texts.STALE_ACTION)
        return
    await _show_results(callback, state, bot, session, query, int(callback_data.value))
    await answer(callback)


# --- period ------------------------------------------------------------------------------------


def _preset(key: str, current: date) -> Period:
    if key == "month":
        return Period(*month_bounds(current))
    if key == "last":
        return Period(*previous_month_bounds(current))
    if key == "year":
        return Period(year_start(current), current)
    return Period()


async def _store_period(state: FSMContext, period: Period) -> None:
    await state.update_data(
        start=period.start.isoformat() if period.start else None,
        end=period.end.isoformat() if period.end else None,
    )


@router.callback_query(ReportFlow.period, _step(RepAction.PERIOD), OnScreen())
async def choose_period(
    callback: CallbackQuery, callback_data: RepCb, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    if callback_data.value == "custom":
        await _ask_period_date(
            callback, state, bot, ReportFlow.period_start, texts.ASK_PERIOD_START
        )
    else:
        await _store_period(state, _preset(callback_data.value, today(settings.zone)))
        await _show_format(callback, state, bot)
    await answer(callback)


@router.message(ReportFlow.period_start, F.text)
async def receive_period_start(
    message: Message, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    assert message.text is not None
    try:
        start = parse_date(message.text, today(settings.zone), allow_future=True)
    except errors.InvalidDate:
        await _ask_period_date(message, state, bot, ReportFlow.period_start, texts.INVALID_DATE)
        return
    await state.update_data(start=start.isoformat())
    await _ask_period_date(message, state, bot, ReportFlow.period_end, texts.ASK_PERIOD_END)


@router.message(ReportFlow.period_end, F.text)
async def receive_period_end(
    message: Message, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    assert message.text is not None
    try:
        end = parse_date(message.text, today(settings.zone), allow_future=True)
    except errors.InvalidDate:
        await _ask_period_date(message, state, bot, ReportFlow.period_end, texts.INVALID_DATE)
        return
    start = date.fromisoformat((await state.get_data())["start"])
    if end < start:
        await _ask_period_date(
            message, state, bot, ReportFlow.period_end, texts.PERIOD_END_BEFORE_START
        )
        return
    await state.update_data(end=end.isoformat())
    await _show_format(message, state, bot)


# --- format and the file -----------------------------------------------------------------------


@router.callback_query(ReportFlow.format, _step(RepAction.FORMAT), OnScreen())
async def send_report(
    callback: CallbackQuery,
    callback_data: RepCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    await answer(callback)
    data = await state.get_data()
    kind = ReportKind(data["kind"])
    if kind == ReportKind.SUMMARY:
        # The cash may have changed while the rates were typed: ask for any missing rate.
        missing = [
            str(currency)
            for currency in currencies_needing_rates(await cash.cash_balances(session))
            if str(currency) not in data["rates"]
        ]
        if missing:
            await state.update_data(pending=missing)
            await _ask_next_rate(callback, state, bot)
            return
    period = None
    if kind in PERIOD_KINDS:
        period = Period(
            date.fromisoformat(data["start"]) if data.get("start") else None,
            date.fromisoformat(data["end"]) if data.get("end") else None,
        )
    chat_id = chat_id_of(callback)
    async with ChatActionSender.upload_document(bot=bot, chat_id=chat_id):
        report = await reports.build_report(
            session,
            kind,
            ReportFormat(callback_data.value),
            generated_by=texts.user_name(user),
            generated_at=datetime.now(settings.zone),
            period=period,
            client_id=data.get("client_id"),
            rates={Currency(code): Decimal(value) for code, value in data.get("rates", {}).items()},
        )
        await bot.send_document(chat_id, BufferedInputFile(report.content, report.filename))
    await bot.send_message(chat_id, texts.MAIN_MENU, reply_markup=main_menu(user))
    await reset_scenario(state, bot, chat_id)


# --- back --------------------------------------------------------------------------------------


@router.callback_query(StateFilter(ReportFlow), _step(RepAction.BACK), OnScreen())
async def back(callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    current = await state.get_state()
    data = await state.get_data()
    kind = ReportKind(data["kind"])
    if current == ReportFlow.client.state and data.get("query") is not None:
        await _show_client_step(callback, state, bot, session)
    elif current == ReportFlow.period_end.state:
        await _ask_period_date(
            callback, state, bot, ReportFlow.period_start, texts.ASK_PERIOD_START
        )
    elif current == ReportFlow.period_start.state:
        await _show_period(callback, state, bot)
    elif current == ReportFlow.period.state and kind == ReportKind.STATEMENT:
        if data.get("from_card"):
            client = await clients.get_client(session, data["client_id"])
            await leave_scenario(callback, state, bot)
            await render_card(bot, callback, session, client)
        else:
            await _show_client_step(callback, state, bot, session)
    elif current == ReportFlow.format.state and kind in PERIOD_KINDS:
        await _show_period(callback, state, bot)
    else:
        await _show_menu(callback, state, bot)
    await answer(callback)
