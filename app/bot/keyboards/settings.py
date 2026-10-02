from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import OpeningAction, OpeningCb, SettingsAction, SettingsCb
from app.bot.keyboards.common import button, home_button, markup
from app.db.models import User


def _cb(action: SettingsAction, helper_id: int = 0) -> SettingsCb:
    return SettingsCb(action=action, helper_id=helper_id)


def settings_menu() -> InlineKeyboardMarkup:
    return markup(
        [button(texts.BTN_HELPERS, _cb(SettingsAction.HELPERS))],
        [button(texts.BTN_OPENING, OpeningCb(action=OpeningAction.SHOW))],
        [home_button()],
    )


def helpers_list(helpers: list[User]) -> InlineKeyboardMarkup:
    rows = [
        [button(texts.helper_button(helper), _cb(SettingsAction.OPEN, helper.id))]
        for helper in helpers
    ]
    return markup(
        *rows,
        [button(texts.BTN_ADD, _cb(SettingsAction.ADD))],
        [button(texts.BTN_BACK, _cb(SettingsAction.HOME)), home_button()],
    )


def ask_username() -> InlineKeyboardMarkup:
    return markup([button(texts.BTN_BACK, _cb(SettingsAction.HELPERS)), home_button()])


def helper_card(helper: User) -> InlineKeyboardMarkup:
    return markup(
        [button(texts.BTN_DELETE, _cb(SettingsAction.DELETE, helper.id))],
        [button(texts.BTN_BACK, _cb(SettingsAction.HELPERS)), home_button()],
    )


def confirm_delete(helper: User) -> InlineKeyboardMarkup:
    return markup(
        [button(texts.BTN_CONFIRM_DELETE, _cb(SettingsAction.CONFIRM_DELETE, helper.id))],
        [button(texts.BTN_BACK, _cb(SettingsAction.OPEN, helper.id)), home_button()],
    )
