from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import PickAction, PickCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.db.models import Client
from app.services.pagination import Page


def _cb(action: PickAction, value: str = "") -> PickCb:
    return PickCb(action=action, value=value)


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, _cb(PickAction.BACK)), home_button()]


def _client_button(client: Client) -> InlineKeyboardButton:
    return button(client.name, _cb(PickAction.CLIENT, str(client.id)))


def choose(recent: list[Client], allow_new: bool) -> InlineKeyboardMarkup:
    rows = [
        [_client_button(client) for client in recent[i : i + 2]] for i in range(0, len(recent), 2)
    ]
    actions = [button(texts.BTN_FIND, _cb(PickAction.SEARCH))] if recent else []
    if allow_new:
        actions.append(button(texts.BTN_NEW_CLIENT, _cb(PickAction.NEW)))
    return markup(*rows, actions, _back_row())


def results(page: Page[Client], allow_new: bool) -> InlineKeyboardMarkup:
    new_row = [button(texts.BTN_NEW_CLIENT, _cb(PickAction.NEW))] if allow_new else []
    return markup(
        *[[_client_button(client)] for client in page.items],
        pager(page, lambda number: _cb(PickAction.RESULTS, str(number))),
        new_row,
        _back_row(),
    )


def back_only() -> InlineKeyboardMarkup:
    return markup(_back_row())


def new_comment() -> InlineKeyboardMarkup:
    return markup([button(texts.BTN_SKIP, _cb(PickAction.SKIP_COMMENT))], _back_row())
