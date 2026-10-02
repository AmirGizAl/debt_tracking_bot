from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import AdjustAction, AdjustCb
from app.bot.keyboards.common import button, home_button, markup
from app.domain.currency import CURRENCIES


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, AdjustCb(action=AdjustAction.BACK)), home_button()]


def currencies() -> InlineKeyboardMarkup:
    row = [
        button(currency, AdjustCb(action=AdjustAction.CURRENCY, currency=currency))
        for currency in CURRENCIES
    ]
    return markup(row, _back_row())


def directions() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_ADJUST_ADD, AdjustCb(action=AdjustAction.DIRECTION, adding=True)),
            button(texts.BTN_ADJUST_REMOVE, AdjustCb(action=AdjustAction.DIRECTION, adding=False)),
        ],
        _back_row(),
    )


def back_only() -> InlineKeyboardMarkup:
    return markup(_back_row())


def confirm() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_SAVE, AdjustCb(action=AdjustAction.SAVE)),
            button(texts.BTN_DONT_SAVE, AdjustCb(action=AdjustAction.DONT_SAVE)),
        ],
        [button(texts.BTN_BACK, AdjustCb(action=AdjustAction.BACK))],
    )
