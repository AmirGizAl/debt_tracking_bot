from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import RepAction, RepCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.db.models import Client
from app.services.pagination import Page
from app.services.reports import ReportFormat, ReportKind
from app.services.reports.data import PeriodPreset

KIND_BUTTONS = (
    (ReportKind.SUMMARY, texts.BTN_REPORT_SUMMARY),
    (ReportKind.RECORDS, texts.BTN_REPORT_RECORDS),
    (ReportKind.CASH, texts.BTN_REPORT_CASH),
    (ReportKind.STATEMENT, texts.BTN_REPORT_STATEMENT),
)

PERIOD_BUTTONS = {
    PeriodPreset.TODAY: texts.BTN_PERIOD_TODAY,
    PeriodPreset.WEEK: texts.BTN_PERIOD_WEEK,
    PeriodPreset.MONTH: texts.BTN_PERIOD_MONTH,
    PeriodPreset.YEAR: texts.BTN_PERIOD_YEAR,
    PeriodPreset.ALL: texts.BTN_ALL_TIME,
}


def _cb(action: RepAction, value: str = "") -> RepCb:
    return RepCb(action=action, value=value)


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, _cb(RepAction.BACK)), home_button()]


def report_menu() -> InlineKeyboardMarkup:
    return markup(
        *[[button(label, _cb(RepAction.KIND, kind))] for kind, label in KIND_BUTTONS],
        [home_button()],
    )


def back_only() -> InlineKeyboardMarkup:
    return markup(_back_row())


def _client_button(client: Client) -> InlineKeyboardButton:
    return button(client.name, _cb(RepAction.CLIENT, str(client.id)))


def client_step(recent: list[Client]) -> InlineKeyboardMarkup:
    rows = [
        [_client_button(client) for client in recent[i : i + 2]] for i in range(0, len(recent), 2)
    ]
    return markup(*rows, [button(texts.BTN_FIND, _cb(RepAction.SEARCH))], _back_row())


def search_results(page: Page[Client]) -> InlineKeyboardMarkup:
    return markup(
        *[[_client_button(client)] for client in page.items],
        pager(page, lambda number: _cb(RepAction.RESULTS, str(number))),
        _back_row(),
    )


def periods() -> InlineKeyboardMarkup:
    def item(preset: PeriodPreset) -> InlineKeyboardButton:
        return button(PERIOD_BUTTONS[preset], _cb(RepAction.PERIOD, preset))

    return markup(
        [item(PeriodPreset.TODAY), item(PeriodPreset.WEEK)],
        [item(PeriodPreset.MONTH), item(PeriodPreset.YEAR)],
        [item(PeriodPreset.ALL)],
        _back_row(),
    )


def formats() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_EXCEL, _cb(RepAction.FORMAT, ReportFormat.XLSX)),
            button(texts.BTN_PDF, _cb(RepAction.FORMAT, ReportFormat.PDF)),
        ],
        _back_row(),
    )
