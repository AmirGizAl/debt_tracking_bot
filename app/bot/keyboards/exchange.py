from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import ExchangeAction, ExchangeCb
from app.bot.keyboards.common import button, home_button, markup
from app.domain.currency import CURRENCIES

MODES = (
    ("now", texts.BTN_MODE_NOW),
    ("received", texts.BTN_MODE_RECEIVED),
    ("paid", texts.BTN_MODE_PAID),
    ("later", texts.BTN_MODE_LATER),
)


def _cb(action: ExchangeAction, value: str = "") -> ExchangeCb:
    return ExchangeCb(action=action, value=value)


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, _cb(ExchangeAction.BACK)), home_button()]


def currencies(action: ExchangeAction, first_step: bool = False) -> InlineKeyboardMarkup:
    row = [button(currency, _cb(action, currency)) for currency in CURRENCIES]
    return markup(row, [home_button()] if first_step else _back_row())


def amount_step(switch_label: str) -> InlineKeyboardMarkup:
    return markup([button(switch_label, _cb(ExchangeAction.SWITCH_SIDE))], _back_row())


def rate_step(last_rate_label: str | None) -> InlineKeyboardMarkup:
    last = [button(last_rate_label, _cb(ExchangeAction.LAST_RATE))] if last_rate_label else []
    return markup(last, _back_row())


def back_only() -> InlineKeyboardMarkup:
    return markup(_back_row())


def modes() -> InlineKeyboardMarkup:
    return markup(
        *[[button(label, _cb(ExchangeAction.MODE, value))] for value, label in MODES],
        _back_row(),
    )


def confirm(instant: bool) -> InlineKeyboardMarkup:
    client_row = [button(texts.BTN_SET_CLIENT, _cb(ExchangeAction.SET_CLIENT))] if instant else []
    return markup(
        [
            button(texts.BTN_SAVE, _cb(ExchangeAction.SAVE)),
            button(texts.BTN_DONT_SAVE, _cb(ExchangeAction.DONT_SAVE)),
        ],
        [
            button(texts.BTN_EDIT_AMOUNT, _cb(ExchangeAction.EDIT_AMOUNT)),
            button(texts.BTN_COMMENT, _cb(ExchangeAction.COMMENT)),
        ],
        client_row,
        [button(texts.BTN_BACK, _cb(ExchangeAction.BACK))],
    )
