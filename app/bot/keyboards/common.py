from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb
from app.db.models import User


def button(text: str, callback: CallbackData) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback.pack())


def markup(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def home_button() -> InlineKeyboardButton:
    return button(texts.BTN_HOME, MenuCb(action=MenuAction.HOME))


def main_menu(user: User) -> InlineKeyboardMarkup:
    def item(text: str, action: MenuAction) -> InlineKeyboardButton:
        return button(text, MenuCb(action=action))

    last_row = [item(texts.BTN_REPORTS, MenuAction.REPORTS)]
    if user.is_owner:
        last_row.append(item(texts.BTN_SETTINGS, MenuAction.SETTINGS))
    return markup(
        [item(texts.BTN_LEND, MenuAction.LEND), item(texts.BTN_REPAY_IN, MenuAction.REPAY_IN)],
        [
            item(texts.BTN_BORROW, MenuAction.BORROW),
            item(texts.BTN_REPAY_OUT, MenuAction.REPAY_OUT),
        ],
        [item(texts.BTN_CLIENTS, MenuAction.CLIENTS), item(texts.BTN_CASH, MenuAction.CASH)],
        last_row,
    )
