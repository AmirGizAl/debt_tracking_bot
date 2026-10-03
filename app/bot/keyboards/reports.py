from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import ReportsAction, ReportsCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.db.models import BusinessDay
from app.services.pagination import Page
from app.services.reports.data import ReportFormat


def _cb(
    action: ReportsAction, day_id: int = 0, page: int = 0, fmt: ReportFormat | None = None
) -> ReportsCb:
    return ReportsCb(action=action, day_id=day_id, page=page, fmt=fmt)


def screen() -> InlineKeyboardMarkup:
    """TZ 13.10."""
    return markup(
        [button(texts.BTN_PRELIMINARY, _cb(ReportsAction.PRELIMINARY))],
        [button(texts.BTN_ARCHIVE, _cb(ReportsAction.ARCHIVE))],
        [button(texts.BTN_WHO_OWES, _cb(ReportsAction.WHO_OWES))],
        [button(texts.BTN_JOURNAL, _cb(ReportsAction.JOURNAL))],
        [button(texts.BTN_MOVEMENT, _cb(ReportsAction.MOVEMENT))],
        [button(texts.BTN_STATEMENT_REPORT, _cb(ReportsAction.STATEMENT))],
        [home_button()],
    )


def archive(page: Page[BusinessDay], zone: ZoneInfo) -> InlineKeyboardMarkup:
    rows = []
    for day in page.items:
        assert day.closed_at is not None and day.surplus is not None
        label = texts.archive_button(day.id, day.closed_at.astimezone(zone).date(), day.surplus)
        rows.append([button(label, _cb(ReportsAction.DAY, day_id=day.id, page=page.page))])
    return markup(
        *rows,
        pager(page, lambda number: _cb(ReportsAction.ARCHIVE, page=number)),
        [button(texts.BTN_BACK, _cb(ReportsAction.SHOW)), home_button()],
    )


def archive_day(day_id: int, page: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(
                texts.BTN_EXCEL, _cb(ReportsAction.DAY_FILE, day_id=day_id, fmt=ReportFormat.XLSX)
            ),
            button(texts.BTN_PDF, _cb(ReportsAction.DAY_FILE, day_id=day_id, fmt=ReportFormat.PDF)),
        ],
        [button(texts.BTN_BACK, _cb(ReportsAction.ARCHIVE, page=page)), home_button()],
    )
