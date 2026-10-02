from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import OpeningAction, OpeningCb, SettingsAction, SettingsCb
from app.bot.keyboards.common import button, home_button, markup
from app.domain.currency import Currency


def _cb(action: OpeningAction, value: str = "") -> OpeningCb:
    return OpeningCb(action=action, value=value)


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, _cb(OpeningAction.BACK)), home_button()]


def screen(can_enter: bool) -> InlineKeyboardMarkup:
    enter = [button(texts.BTN_ENTER, _cb(OpeningAction.ENTER))] if can_enter else []
    return markup(
        enter,
        [button(texts.BTN_BACK, SettingsCb(action=SettingsAction.HOME)), home_button()],
    )


def currencies(free: list[Currency]) -> InlineKeyboardMarkup:
    return markup([button(c, _cb(OpeningAction.CURRENCY, c)) for c in free], _back_row())


def back_only() -> InlineKeyboardMarkup:
    return markup(_back_row())


def confirm() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_SAVE, _cb(OpeningAction.SAVE)),
            button(texts.BTN_DONT_SAVE, _cb(OpeningAction.DONT_SAVE)),
        ],
        [button(texts.BTN_BACK, _cb(OpeningAction.BACK))],
    )
