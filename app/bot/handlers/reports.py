"""«Отчёты» and the archive of closed days (TZ 8.5, 13.10). The archive is a view: its buttons
always work, a file comes under the screen."""

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb, ReportsAction, ReportsCb
from app.bot.keyboards import reports as kb
from app.bot.ui import answer, chat_id_of, leave_any, leave_scenario, show_screen
from app.config import Settings
from app.db.models import User
from app.domain import errors
from app.services import days, reports

router = Router(name="reports")


async def show_reports(event: Message | CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await leave_any(event, state, bot)
    await show_screen(event, bot, texts.REPORTS_TITLE, kb.screen())


@router.callback_query(MenuCb.filter(F.action == MenuAction.REPORTS))
@router.callback_query(ReportsCb.filter(F.action == ReportsAction.SHOW))
async def open_reports(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await show_reports(callback, state, bot)
    await answer(callback)


# --- «Кто кому должен» (TZ 14.2) -----------------------------------------------------------------


@router.callback_query(ReportsCb.filter(F.action == ReportsAction.WHO_OWES))
async def who_owes(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await leave_scenario(callback, state, bot)
    text = f"{texts.report_title_html(texts.WHO_OWES_TITLE)}\n\n{texts.CHOOSE_FORMAT}"
    await show_screen(callback, bot, text, kb.who_owes())
    await answer(callback)


@router.callback_query(ReportsCb.filter(F.action == ReportsAction.WHO_OWES_FILE))
async def who_owes_file(
    callback: CallbackQuery,
    callback_data: ReportsCb,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Obligations right now; a view: the file comes under the screen."""
    if callback_data.fmt is None:
        await answer(callback, texts.STALE_ACTION)
        return
    await answer(callback)
    chat_id = chat_id_of(callback)
    async with ChatActionSender.upload_document(bot=bot, chat_id=chat_id):
        report = await reports.who_owes_file(
            session,
            callback_data.fmt,
            generated_by=texts.user_name(user),
            generated_at=datetime.now(settings.zone),
            zone=settings.zone,
        )
    await bot.send_document(chat_id, BufferedInputFile(report.content, report.filename))


# --- the archive (TZ 8.5) ------------------------------------------------------------------------


@router.callback_query(ReportsCb.filter(F.action == ReportsAction.ARCHIVE))
async def archive(
    callback: CallbackQuery,
    callback_data: ReportsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """Closed days, the newest first: «День №3 · 02.10.2026 · +1 315»."""
    await leave_scenario(callback, state, bot)
    page = await days.closed_days(session, callback_data.page)
    text = texts.ARCHIVE_TITLE if page.total else f"{texts.ARCHIVE_TITLE}\n{texts.ARCHIVE_EMPTY}"
    await show_screen(callback, bot, text, kb.archive(page, settings.zone))
    await answer(callback)


@router.callback_query(ReportsCb.filter(F.action == ReportsAction.DAY))
async def archive_day(
    callback: CallbackQuery,
    callback_data: ReportsCb,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        day, report = await days.archived_report(session, callback_data.day_id)
    except errors.DayNotFound:
        await answer(callback, texts.STALE_ACTION)
        return
    assert day.closed_at is not None
    await leave_scenario(callback, state, bot)
    text = texts.archive_day(day.id, day.closed_at.astimezone(settings.zone).date(), report)
    await show_screen(callback, bot, text, kb.archive_day(day.id, callback_data.page))
    await answer(callback)


@router.callback_query(ReportsCb.filter(F.action == ReportsAction.DAY_FILE))
async def archive_file(
    callback: CallbackQuery,
    callback_data: ReportsCb,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """The report of a closed day from its snapshot; any user, any time (TZ 8.5)."""
    if callback_data.fmt is None:
        await answer(callback, texts.STALE_ACTION)
        return
    chat_id = chat_id_of(callback)
    try:
        async with ChatActionSender.upload_document(bot=bot, chat_id=chat_id):
            report = await reports.closed_day_file(
                session,
                callback_data.day_id,
                callback_data.fmt,
                generated_by=texts.user_name(user),
                generated_at=datetime.now(settings.zone),
                zone=settings.zone,
            )
    except errors.DayNotFound:
        await answer(callback, texts.STALE_ACTION)
        return
    await answer(callback)
    await bot.send_document(chat_id, BufferedInputFile(report.content, report.filename))
