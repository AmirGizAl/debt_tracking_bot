from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import (
    OpeningDebtAction,
    OpeningDebtCb,
    RecordAction,
    RecordCb,
    SettingsAction,
    SettingsCb,
)
from app.bot.keyboards.common import button, home_button, markup, pager
from app.domain.currency import CURRENCIES
from app.domain.entries import Book
from app.services.opening_debts import OpeningDebt
from app.services.pagination import Page


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, OpeningDebtCb(action=OpeningDebtAction.BACK)), home_button()]


def screen(page: Page[OpeningDebt]) -> InlineKeyboardMarkup:
    """The debts that are not cancelled; a debt opens its record, where it can be cancelled."""
    rows = [
        [
            button(
                texts.opening_debt_button(debt.client, debt.book, debt.currency, debt.amount),
                RecordCb(action=RecordAction.OPEN, record_id=debt.record_id),
            )
        ]
        for debt in page.items
    ]
    return markup(
        *rows,
        pager(page, lambda number: OpeningDebtCb(action=OpeningDebtAction.SHOW, page=number)),
        [button(texts.BTN_ENTER, OpeningDebtCb(action=OpeningDebtAction.ENTER))],
        [button(texts.BTN_BACK, SettingsCb(action=SettingsAction.HOME)), home_button()],
    )


def currencies() -> InlineKeyboardMarkup:
    row = [
        button(currency, OpeningDebtCb(action=OpeningDebtAction.CURRENCY, currency=currency))
        for currency in CURRENCIES
    ]
    return markup(row, _back_row())


def books() -> InlineKeyboardMarkup:
    return markup(
        [
            button(
                texts.BTN_BOOK_LOAN, OpeningDebtCb(action=OpeningDebtAction.BOOK, book=Book.LOAN)
            ),
            button(
                texts.BTN_BOOK_EXCHANGE,
                OpeningDebtCb(action=OpeningDebtAction.BOOK, book=Book.EXCHANGE),
            ),
        ],
        _back_row(),
    )


def directions() -> InlineKeyboardMarkup:
    return markup(
        [
            button(
                texts.BTN_OWED_TO_US, OpeningDebtCb(action=OpeningDebtAction.DIRECTION, owed=True)
            )
        ],
        [button(texts.BTN_WE_OWE, OpeningDebtCb(action=OpeningDebtAction.DIRECTION, owed=False))],
        _back_row(),
    )


def back_only() -> InlineKeyboardMarkup:
    return markup(_back_row())


def confirm() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_SAVE, OpeningDebtCb(action=OpeningDebtAction.SAVE)),
            button(texts.BTN_DONT_SAVE, OpeningDebtCb(action=OpeningDebtAction.DONT_SAVE)),
        ],
        [button(texts.BTN_BACK, OpeningDebtCb(action=OpeningDebtAction.BACK))],
    )
