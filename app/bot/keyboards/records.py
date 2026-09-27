from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import (
    ClientsAction,
    ClientsCb,
    HistoryCb,
    RecordAction,
    RecordCb,
    RevAction,
    RevCb,
)
from app.bot.keyboards.common import button, home_button, markup, pager
from app.services.operations import RecordLine
from app.services.pagination import Page


def record_card(operation_id: int, client_id: int, can_cancel: bool) -> InlineKeyboardMarkup:
    cancel_row = (
        [
            button(
                texts.BTN_CANCEL_RECORD,
                RecordCb(action=RecordAction.REVERSE, operation_id=operation_id),
            )
        ]
        if can_cancel
        else []
    )
    return markup(
        cancel_row,
        [
            button(texts.BTN_CLIENT, ClientsCb(action=ClientsAction.OPEN, client_id=client_id)),
            home_button(),
        ],
    )


def history(client_id: int, page: Page[RecordLine]) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                texts.history_button(
                    item_id=line.id,
                    op_type=line.type,
                    op_date=line.op_date,
                    debt_amount=line.debt_amount,
                    debt_currency=line.debt_currency,
                    reversal_of_id=line.reversal_of_id,
                    reversed_by_id=line.reversed_by_id,
                ),
                RecordCb(action=RecordAction.OPEN, operation_id=line.id),
            )
        ]
        for line in page.items
    ]
    return markup(
        *rows,
        pager(page, lambda number: HistoryCb(client_id=client_id, page=number)),
        [
            button(texts.BTN_BACK, ClientsCb(action=ClientsAction.OPEN, client_id=client_id)),
            home_button(),
        ],
    )


def cancel_reason(operation_id: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_BACK, RecordCb(action=RecordAction.OPEN, operation_id=operation_id)),
            home_button(),
        ]
    )


def confirm_cancel() -> InlineKeyboardMarkup:
    return markup(
        [button(texts.BTN_CONFIRM_CANCEL, RevCb(action=RevAction.CONFIRM))],
        [button(texts.BTN_BACK, RevCb(action=RevAction.BACK)), home_button()],
    )
