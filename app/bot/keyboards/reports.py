from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import RepAction, RepCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.db.models import Client
from app.services.pagination import Page
from app.services.reports import ReportFormat, ReportKind

KIND_BUTTONS = (
    (ReportKind.SUMMARY, texts.BTN_REPORT_SUMMARY),
    (ReportKind.DEBTS, texts.BTN_REPORT_DEBTS),
    (ReportKind.RECORDS, texts.BTN_REPORT_RECORDS),
    (ReportKind.CASH, texts.BTN_REPORT_CASH),
    (ReportKind.STATEMENT, texts.BTN_REPORT_STATEMENT),
)

PERIOD_PRESETS = {
    "month": texts.BTN_THIS_MONTH,
    "last": texts.BTN_LAST_MONTH,
    "year": texts.BTN_THIS_YEAR,
    "all": texts.BTN_ALL_TIME,
    "custom": texts.BTN_CUSTOM_PERIOD,
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
    def item(key: str) -> InlineKeyboardButton:
        return button(PERIOD_PRESETS[key], _cb(RepAction.PERIOD, key))

    return markup(
        [item("month"), item("last")],
        [item("year"), item("all")],
        [item("custom")],
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
