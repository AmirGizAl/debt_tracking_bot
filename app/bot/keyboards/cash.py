from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import AdjAction, AdjCb, CashAction, CashCb, RecordAction, RecordCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.db.models import User
from app.domain.currency import CURRENCIES
from app.services.cash import Movement
from app.services.pagination import Page


def cash_screen(user: User) -> InlineKeyboardMarkup:
    adjust_row = (
        [button(texts.BTN_ADJUST, CashCb(action=CashAction.ADJUST))] if user.is_owner else []
    )
    return markup(
        [button(texts.BTN_MOVEMENTS, CashCb(action=CashAction.MOVEMENTS))],
        adjust_row,
        [home_button()],
    )


def _movement_button(movement: Movement) -> InlineKeyboardButton:
    label = texts.movement_button(
        is_adjustment=movement.is_adjustment,
        item_id=movement.item_id,
        day=movement.day,
        currency=movement.currency,
        amount=movement.amount,
        op_type=movement.op_type,
        title=movement.title,
        reversal_of_id=movement.reversal_of_id,
        reversed_by_id=movement.reversed_by_id,
    )
    if movement.is_adjustment:
        callback = CashCb(action=CashAction.ADJUSTMENT_INFO, item_id=movement.item_id)
        return button(label, callback)
    return button(label, RecordCb(action=RecordAction.OPEN, operation_id=movement.item_id))


def movements(page: Page[Movement]) -> InlineKeyboardMarkup:
    return markup(
        *[[_movement_button(movement)] for movement in page.items],
        pager(page, lambda number: CashCb(action=CashAction.MOVEMENTS, page=number)),
        [button(texts.BTN_CASH_BACK, CashCb(action=CashAction.SHOW)), home_button()],
    )


def _adj(action: AdjAction, value: str = "") -> AdjCb:
    return AdjCb(action=action, value=value)


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, _adj(AdjAction.BACK)), home_button()]


def adjust_currency() -> InlineKeyboardMarkup:
    return markup(
        [button(currency, _adj(AdjAction.CURRENCY, currency)) for currency in CURRENCIES],
        [button(texts.BTN_BACK, CashCb(action=CashAction.SHOW)), home_button()],
    )


def adjust_direction() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_ADD_MONEY, _adj(AdjAction.ADD)),
            button(texts.BTN_REMOVE_MONEY, _adj(AdjAction.REMOVE)),
        ],
        _back_row(),
    )


def adjust_back() -> InlineKeyboardMarkup:
    return markup(_back_row())


def adjust_confirm() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_SAVE, _adj(AdjAction.SAVE)),
            button(texts.BTN_DONT_SAVE, _adj(AdjAction.DONT_SAVE)),
        ],
        [button(texts.BTN_BACK, _adj(AdjAction.BACK))],
    )
