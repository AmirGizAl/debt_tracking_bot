from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import OpAction, OpCb, RecordAction, RecordCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.db.models import Client
from app.domain.currency import CURRENCIES, Currency
from app.services.pagination import Page


def _cb(action: OpAction, value: str = "") -> OpCb:
    return OpCb(action=action, value=value)


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, _cb(OpAction.BACK)), home_button()]


def _client_button(client: Client) -> InlineKeyboardButton:
    return button(client.name, _cb(OpAction.CLIENT, str(client.id)))


def client_step(recent: list[Client]) -> InlineKeyboardMarkup:
    rows = [
        [_client_button(client) for client in recent[i : i + 2]] for i in range(0, len(recent), 2)
    ]
    find_row = [button(texts.BTN_FIND, _cb(OpAction.SEARCH))] if recent else []
    return markup(
        *rows,
        [*find_row, button(texts.BTN_NEW_CLIENT, _cb(OpAction.NEW_CLIENT))],
        [home_button()],
    )


def back_only() -> InlineKeyboardMarkup:
    return markup(_back_row())


def search_results(page: Page[Client]) -> InlineKeyboardMarkup:
    return markup(
        *[[_client_button(client)] for client in page.items],
        pager(page, lambda number: _cb(OpAction.RESULTS, str(number))),
        [button(texts.BTN_NEW_CLIENT, _cb(OpAction.NEW_CLIENT))],
        _back_row(),
    )


def skip_or_back(skip: OpAction) -> InlineKeyboardMarkup:
    return markup([button(texts.BTN_SKIP, _cb(skip))], _back_row())


def currencies() -> InlineKeyboardMarkup:
    return markup(
        [button(currency, _cb(OpAction.CURRENCY, currency)) for currency in CURRENCIES],
        _back_row(),
    )


def debt_currencies(balances: dict[Currency, Decimal]) -> InlineKeyboardMarkup:
    return markup(
        *[
            [
                button(
                    texts.debt_currency_button(currency, balance),
                    _cb(OpAction.CURRENCY, currency),
                )
            ]
            for currency, balance in balances.items()
        ],
        _back_row(),
    )


def pay_mode() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_SAME_CURRENCY, _cb(OpAction.SAME_CURRENCY)),
            button(texts.BTN_OTHER_CURRENCY, _cb(OpAction.OTHER_CURRENCY)),
        ],
        _back_row(),
    )


def pay_currencies(debt_currency: Currency) -> InlineKeyboardMarkup:
    return markup(
        [
            button(currency, _cb(OpAction.PAY_CURRENCY, currency))
            for currency in CURRENCIES
            if currency != debt_currency
        ],
        _back_row(),
    )


def dates() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_TODAY, _cb(OpAction.TODAY)),
            button(texts.BTN_YESTERDAY, _cb(OpAction.YESTERDAY)),
            button(texts.BTN_OTHER_DATE, _cb(OpAction.OTHER_DATE)),
        ],
        _back_row(),
    )


def confirm() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_SAVE, _cb(OpAction.SAVE)),
            button(texts.BTN_DONT_SAVE, _cb(OpAction.DONT_SAVE)),
        ],
        [button(texts.BTN_BACK, _cb(OpAction.BACK))],
    )


def open_record(operation_id: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(
                texts.BTN_OPEN_RECORD,
                RecordCb(action=RecordAction.OPEN, operation_id=operation_id),
            )
        ]
    )
