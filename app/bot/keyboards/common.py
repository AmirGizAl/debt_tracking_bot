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


# Rows of the main menu and of the panel (TZ 13.2); the last row is for owners only.
MENU_ROWS: tuple[tuple[tuple[str, MenuAction], ...], ...] = (
    ((texts.BTN_EXCHANGE, MenuAction.EXCHANGE),),
    ((texts.BTN_TO_PAY, MenuAction.TO_PAY), (texts.BTN_TO_RECEIVE, MenuAction.TO_RECEIVE)),
    ((texts.BTN_LOANS, MenuAction.LOANS), (texts.BTN_CLIENTS, MenuAction.CLIENTS)),
    ((texts.BTN_BALANCES, MenuAction.BALANCES), (texts.BTN_REPORTS, MenuAction.REPORTS)),
)
OWNER_ROW: tuple[tuple[str, MenuAction], ...] = (
    (texts.BTN_CLOSE_DAY, MenuAction.CLOSE_DAY),
    (texts.BTN_SETTINGS, MenuAction.SETTINGS),
)


def _menu_rows(user: User) -> list[tuple[tuple[str, MenuAction], ...]]:
    return [*MENU_ROWS, OWNER_ROW] if user.is_owner else list(MENU_ROWS)


def main_menu(user: User) -> InlineKeyboardMarkup:
    return markup(
        *[[button(text, MenuCb(action=action)) for text, action in row] for row in _menu_rows(user)]
    )


def panel(user: User) -> ReplyKeyboardMarkup:
    """Section panel under the input field, always shown; same layout as the main menu."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text, _ in row] for row in _menu_rows(user)],
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
