"""«Журнал записей», «Движение балансов» and «Выписка по клиенту» (TZ 13.10, 14.3-14.5).

(the client of a statement ->) a period: «Текущий день», «Закрытый день», «Период по датам»;
for a statement «Всё время» or «Период по датам» -> «Excel» or «PDF». The screen with the
format stays after a file: the other format is one tap away.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import (
    ClientsAction,
    ClientsCb,
    ReportsAction,
    ReportsCb,
    ReportStep,
    ReportStepCb,
)
from app.bot.flows import client_picker, records
from app.bot.flows.records import Event, StoredForm
from app.bot.handlers.clients import show_card
from app.bot.handlers.reports import show_reports
from app.bot.keyboards import reports as kb
from app.bot.states import ReportFlow
from app.bot.ui import OnScreen, answer, chat_id_of, finish, leave_scenario, show_step
from app.config import Settings
from app.db.models import BusinessDay, Client, User
from app.domain import errors
from app.domain.dates import format_date, parse_date
from app.services import clients, days, reports
from app.services.reports.data import Period

router = Router(name="period_reports")

PICK_FOR_STATEMENT = "statement"


class ReportKind(StrEnum):
    JOURNAL = "journal"
    MOVEMENT = "movement"
    STATEMENT = "statement"


class PeriodChoice(StrEnum):
    CURRENT_DAY = "day"
    CLOSED_DAY = "closed"
    DATES = "dates"
    ALL_TIME = "all"


TITLES = {
    ReportKind.JOURNAL: texts.JOURNAL_TITLE,
    ReportKind.MOVEMENT: texts.MOVEMENT_TITLE,
    ReportKind.STATEMENT: texts.STATEMENT_TITLE,
}
CHOICES = {
    PeriodChoice.CURRENT_DAY: texts.BTN_CURRENT_DAY,
    PeriodChoice.CLOSED_DAY: texts.BTN_CLOSED_DAY,
    PeriodChoice.DATES: texts.BTN_DATES,
    PeriodChoice.ALL_TIME: texts.BTN_ALL_TIME,
}


@dataclass
class Form(StoredForm):
    kind: ReportKind
    client_id: int | None = None
    client_name: str | None = None
    from_card: bool = False  # «Выписка» on the client card: «Назад» leads there
    choice: PeriodChoice | None = None
    day_id: int | None = None
    start: str | None = None  # ISO dates of «Период по датам»
    end: str | None = None
    page: int = 0  # the page of the closed days

    @property
    def choices(self) -> list[PeriodChoice]:
        """TZ 13.10 for the journal and the movement, TZ 14.5 for the statement."""
        if self.kind == ReportKind.STATEMENT:
            return [PeriodChoice.ALL_TIME, PeriodChoice.DATES]
        return [PeriodChoice.CURRENT_DAY, PeriodChoice.CLOSED_DAY, PeriodChoice.DATES]

    def period(self) -> Period:
        if self.choice in (PeriodChoice.CURRENT_DAY, PeriodChoice.CLOSED_DAY):
            return Period(day_id=self.day_id)
        if self.choice == PeriodChoice.DATES:
            assert self.start is not None and self.end is not None
            return Period(start=date.fromisoformat(self.start), end=date.fromisoformat(self.end))
        return Period()

    def head(self) -> list[str]:
        """The title of the steps and the client of a statement."""
        lines = [texts.report_title_html(TITLES[self.kind])]
        if self.client_name is not None:
            lines.append(texts.client_line(self.client_name))
        return lines


def _step(action: ReportStep):
    return ReportStepCb.filter(F.action == action)


async def _form(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> Form | None:
    return await records.current_form(Form, event, state, bot, session, user)


async def _store(state: FSMContext, form: Form) -> None:
    await state.update_data(form.dump())


# --- steps ---------------------------------------------------------------------------------------


async def show_period(event: Event, state: FSMContext, bot: Bot, form: Form) -> None:
    head = form.head()
    text = texts.step_text(head[0], head[1:], texts.ASK_PERIOD)
    choices = [(str(choice), CHOICES[choice]) for choice in form.choices]
    await state.set_state(ReportFlow.period)
    await show_step(event, state, bot, text, kb.periods(choices))


async def show_closed_days(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, settings: Settings, form: Form
) -> None:
    page = await days.closed_days(session, form.page)
    head = form.head()
    text = texts.step_text(head[0], head[1:], texts.ASK_CLOSED_DAY)
    await state.set_state(ReportFlow.closed_day)
    await show_step(event, state, bot, text, kb.closed_days(page, settings.zone))


async def show_date(
    event: Event, state: FSMContext, bot: Bot, form: Form, *, end: bool, problem: str | None = None
) -> None:
    head = form.head()
    if end:
        assert form.start is not None
        head.append(f"С {format_date(date.fromisoformat(form.start))}")
    question = texts.ASK_END_DATE if end else texts.ASK_START_DATE
    await state.set_state(ReportFlow.end_date if end else ReportFlow.start_date)
    await show_step(
        event, state, bot, texts.step_text(head[0], head[1:], question, problem), kb.back_only()
    )


async def _scope(session: AsyncSession, settings: Settings, form: Form) -> str:
    period = form.period()
    if period.day_id is not None:
        day = await session.get(BusinessDay, period.day_id, populate_existing=True)
        assert day is not None
        closed_on = day.closed_at.astimezone(settings.zone).date() if day.closed_at else None
        return texts.day_scope(day.id, closed_on)
    if period.start is not None and period.end is not None:
        return texts.dates_scope(period.start, period.end)
    return texts.PERIOD_ALL_TIME


async def show_file(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, settings: Settings, form: Form
) -> None:
    head = form.head()
    lines = [*head[1:], await _scope(session, settings, form)]
    await state.set_state(ReportFlow.file)
    await show_step(
        event, state, bot, texts.step_text(head[0], lines, texts.CHOOSE_FORMAT), kb.formats()
    )


# --- entry points --------------------------------------------------------------------------------


@router.callback_query(
    ReportsCb.filter(F.action.in_({ReportsAction.JOURNAL, ReportsAction.MOVEMENT}))
)
async def start_period_report(
    callback: CallbackQuery, callback_data: ReportsCb, state: FSMContext, bot: Bot
) -> None:
    kind = (
        ReportKind.JOURNAL if callback_data.action == ReportsAction.JOURNAL else ReportKind.MOVEMENT
    )
    await leave_scenario(callback, state, bot)
    form = Form(kind=kind)
    await state.set_data(form.dump())
    await show_period(callback, state, bot, form)
    await answer(callback)


@router.callback_query(ReportsCb.filter(F.action == ReportsAction.STATEMENT))
async def start_statement(
    callback: CallbackQuery, state: FSMContext, bot: Bot, session: AsyncSession
) -> None:
    await leave_scenario(callback, state, bot)
    await state.set_data(Form(kind=ReportKind.STATEMENT).dump())
    title = texts.report_title_html(texts.STATEMENT_TITLE)
    await client_picker.start(callback, state, bot, session, target=PICK_FOR_STATEMENT, title=title)
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
        await answer(callback, texts.CLIENT_NOT_FOUND)
        return
    await leave_scenario(callback, state, bot)
    form = Form(
        kind=ReportKind.STATEMENT, client_id=client.id, client_name=client.name, from_card=True
    )
    await state.set_data(form.dump())
    await show_period(callback, state, bot, form)
    await answer(callback)


async def _client_picked(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User, client: Client
) -> None:
    form = await _form(event, state, bot, session, user)
    if form is None:
        return
    form.client_id, form.client_name = client.id, client.name
    await _store(state, form)
    await show_period(event, state, bot, form)


async def _back_to_reports(
    event: Event, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    await show_reports(event, state, bot)


# Decision 17: the statement chooses among existing clients only.
client_picker.register(
    PICK_FOR_STATEMENT, client_picker.Target(_client_picked, _back_to_reports, allow_new=False)
)


# --- the period ----------------------------------------------------------------------------------


@router.callback_query(ReportFlow.period, _step(ReportStep.PERIOD), OnScreen())
async def choose_period(
    callback: CallbackQuery,
    callback_data: ReportStepCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    try:
        choice = PeriodChoice(callback_data.value)
    except ValueError:
        choice = None
    if choice not in form.choices:
        await answer(callback, texts.STALE_ACTION)
        return
    form.choice, form.day_id, form.page = choice, None, 0
    if choice == PeriodChoice.CLOSED_DAY:
        if (await days.closed_days(session, 0)).total == 0:
            await answer(callback, texts.NO_CLOSED_DAYS, alert=True)
            return
        await _store(state, form)
        await show_closed_days(callback, state, bot, session, settings, form)
    elif choice == PeriodChoice.DATES:
        await _store(state, form)
        await show_date(callback, state, bot, form, end=False)
    else:
        if choice == PeriodChoice.CURRENT_DAY:
            form.day_id = await days.open_day_number(session)
        await _store(state, form)
        await show_file(callback, state, bot, session, settings, form)
    await answer(callback)


@router.callback_query(ReportFlow.closed_day, _step(ReportStep.DAYS), OnScreen())
async def closed_days_page(
    callback: CallbackQuery,
    callback_data: ReportStepCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    form.page = callback_data.page
    await _store(state, form)
    await show_closed_days(callback, state, bot, session, settings, form)
    await answer(callback)


@router.callback_query(ReportFlow.closed_day, _step(ReportStep.DAY), OnScreen())
async def choose_closed_day(
    callback: CallbackQuery,
    callback_data: ReportStepCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    form.day_id = callback_data.day_id
    await _store(state, form)
    await show_file(callback, state, bot, session, settings, form)
    await answer(callback)


@router.message(ReportFlow.start_date, F.text)
async def receive_start(
    message: Message, state: FSMContext, bot: Bot, session: AsyncSession, user: User
) -> None:
    assert message.text is not None
    form = await _form(message, state, bot, session, user)
    if form is None:
        return
    try:
        start = parse_date(message.text)
    except errors.InvalidDate:
        await show_date(message, state, bot, form, end=False, problem=texts.INVALID_DATE)
        return
    form.start, form.end = start.isoformat(), None
    await _store(state, form)
    await show_date(message, state, bot, form, end=True)


@router.message(ReportFlow.end_date, F.text)
async def receive_end(
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
    assert form.start is not None
    try:
        end = parse_date(message.text)
    except errors.InvalidDate:
        await show_date(message, state, bot, form, end=True, problem=texts.INVALID_DATE)
        return
    if end < date.fromisoformat(form.start):
        await show_date(message, state, bot, form, end=True, problem=texts.END_BEFORE_START)
        return
    form.end = end.isoformat()
    await _store(state, form)
    await show_file(message, state, bot, session, settings, form)


# --- the file ------------------------------------------------------------------------------------


@router.callback_query(ReportFlow.file, _step(ReportStep.FILE), OnScreen())
async def send_file(
    callback: CallbackQuery,
    callback_data: ReportStepCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    form = await _form(callback, state, bot, session, user)
    if form is None:
        return
    if callback_data.fmt is None:
        await answer(callback, texts.STALE_ACTION)
        return
    await answer(callback)
    chat_id = chat_id_of(callback)
    options = {
        "generated_by": texts.user_name(user),
        "generated_at": datetime.now(settings.zone),
        "zone": settings.zone,
    }
    try:
        async with ChatActionSender.upload_document(bot=bot, chat_id=chat_id):
            if form.kind == ReportKind.JOURNAL:
                report = await reports.journal_file(
                    session, form.period(), callback_data.fmt, **options
                )
            elif form.kind == ReportKind.MOVEMENT:
                report = await reports.movement_file(
                    session, form.period(), callback_data.fmt, **options
                )
            else:
                assert form.client_id is not None
                report = await reports.statement_file(
                    session, form.client_id, form.period(), callback_data.fmt, **options
                )
    except errors.ClientNotFound:
        await finish(bot, state, chat_id, user, session, texts.CLIENT_NOT_FOUND)
        return
    await bot.send_document(chat_id, BufferedInputFile(report.content, report.filename))


# --- back ----------------------------------------------------------------------------------------


@router.callback_query(StateFilter(ReportFlow), _step(ReportStep.BACK), OnScreen())
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
    current = await state.get_state()
    if current == ReportFlow.file.state and form.choice == PeriodChoice.CLOSED_DAY:
        await show_closed_days(callback, state, bot, session, settings, form)
    elif current == ReportFlow.file.state and form.choice == PeriodChoice.DATES:
        await show_date(callback, state, bot, form, end=True)
    elif current == ReportFlow.end_date.state:
        await show_date(callback, state, bot, form, end=False)
    elif current != ReportFlow.period.state:
        await show_period(callback, state, bot, form)
    elif form.kind != ReportKind.STATEMENT:
        await show_reports(callback, state, bot)
    elif form.from_card and form.client_id is not None:
        await leave_scenario(callback, state, bot)
        try:
            client = await clients.get_client(session, form.client_id)
        except errors.ClientNotFound:
            await show_reports(callback, state, bot)
        else:
            await show_card(callback, bot, session, client)
    else:
        await client_picker.start(
            callback,
            state,
            bot,
            session,
            target=PICK_FOR_STATEMENT,
            title=texts.report_title_html(texts.STATEMENT_TITLE),
        )
    await answer(callback)
