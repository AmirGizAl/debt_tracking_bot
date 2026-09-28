from collections.abc import Callable
from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot import texts
from app.bot.callbacks import MenuAction, MenuCb, NoopCb
from app.db.models import User
from app.services.pagination import Page


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


def panel(user: User) -> ReplyKeyboardMarkup:
    """Section panel under the input field, always shown; same layout as the main menu."""

    def item(text: str) -> KeyboardButton:
        return KeyboardButton(text=text)

    last_row = [item(texts.BTN_REPORTS)]
    if user.is_owner:
        last_row.append(item(texts.BTN_SETTINGS))
    return ReplyKeyboardMarkup(
        keyboard=[
            [item(texts.BTN_LEND), item(texts.BTN_REPAY_IN)],
            [item(texts.BTN_BORROW), item(texts.BTN_REPAY_OUT)],
            [item(texts.BTN_CLIENTS), item(texts.BTN_CASH)],
            last_row,
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def pager(page: Page[Any], make: Callable[[int], CallbackData]) -> list[InlineKeyboardButton]:
    """'‹ 2/5 ›' row; empty when everything fits on one page."""
    if page.pages <= 1:
        return []
    row = []
    if page.has_prev:
        row.append(button(texts.BTN_PREV_PAGE, make(page.page - 1)))
    row.append(button(f"{page.page + 1}/{page.pages}", NoopCb()))
    if page.has_next:
        row.append(button(texts.BTN_NEXT_PAGE, make(page.page + 1)))
    return row
