from zoneinfo import ZoneInfo

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import (
    BalancesAction,
    BalancesCb,
    ClientsAction,
    ClientsCb,
    RecordAction,
    RecordCb,
    RecordSource,
)
from app.bot.keyboards.common import button, home_button, markup, pager
from app.db.models import Operation
from app.services.journal import RecordRow
from app.services.pagination import Page


def open_record(record_id: int) -> InlineKeyboardMarkup:
    """«Открыть запись» under a result or a notification (a view: always valid)."""
    record = RecordCb(action=RecordAction.OPEN, record_id=record_id)
    return markup([button(texts.BTN_OPEN_RECORD, record)])


def day_records(page: Page[RecordRow]) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                texts.record_button(row.operation, row.client_name, row.reversed_by),
                RecordCb(
                    action=RecordAction.OPEN,
                    record_id=row.operation.id,
                    source=RecordSource.DAY,
                    page=page.page,
                ),
            )
        ]
        for row in page.items
    ]
    return markup(
        *rows,
        pager(page, lambda number: BalancesCb(action=BalancesAction.RECORDS, page=number)),
        [button(texts.BTN_BACK, BalancesCb(action=BalancesAction.SHOW)), home_button()],
    )


def _history(client_id: int, page: int) -> ClientsCb:
    return ClientsCb(action=ClientsAction.HISTORY, client_id=client_id, page=page)


def history(client_id: int, page: Page[RecordRow], zone: ZoneInfo) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                texts.history_button(row.operation, row.reversed_by, zone),
                RecordCb(
                    action=RecordAction.OPEN,
                    record_id=row.operation.id,
                    source=RecordSource.HISTORY,
                    client_id=client_id,
                    page=page.page,
                ),
            )
        ]
        for row in page.items
    ]
    return markup(
        *rows,
        pager(page, lambda number: _history(client_id, number)),
        [
            button(texts.BTN_BACK, ClientsCb(action=ClientsAction.OPEN, client_id=client_id)),
            home_button(),
        ],
    )


def _list_of(source: RecordSource | None, client_id: int, page: int) -> CallbackData | None:
    """The list the card was opened from."""
    if source == RecordSource.DAY:
        return BalancesCb(action=BalancesAction.RECORDS, page=page)
    if source == RecordSource.HISTORY:
        return _history(client_id, page)
    return None


def record_card(
    operation: Operation,
    can_cancel: bool,
    source: RecordSource | None = None,
    client_id: int = 0,
    page: int = 0,
) -> InlineKeyboardMarkup:
    """TZ 13.8: «Отменить запись» (TZ 11.1), «Клиент», «В меню»; «Назад» to the list."""
    cancel = RecordCb(
        action=RecordAction.CANCEL,
        record_id=operation.id,
        source=source,
        client_id=client_id,
        page=page,
    )
    client = []
    if operation.client_id is not None:
        card = ClientsCb(action=ClientsAction.OPEN, client_id=operation.client_id)
        client.append(button(texts.BTN_CLIENT, card))
    back = _list_of(source, client_id, page)
    return markup(
        [button(texts.BTN_CANCEL_RECORD, cancel)] if can_cancel else [],
        client,
        [button(texts.BTN_BACK, back), home_button()] if back is not None else [home_button()],
    )


def cancel_reason() -> InlineKeyboardMarkup:
    return markup([button(texts.BTN_BACK, RecordCb(action=RecordAction.BACK)), home_button()])


def confirm_cancel() -> InlineKeyboardMarkup:
    """TZ 11.3: «Да, отменить» and «Назад»."""
    return markup(
        [button(texts.BTN_CONFIRM_CANCEL, RecordCb(action=RecordAction.CONFIRM))],
        [button(texts.BTN_BACK, RecordCb(action=RecordAction.BACK))],
    )
