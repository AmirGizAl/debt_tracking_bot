from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import ClientsAction, ClientsCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.db.models import Client
from app.services.pagination import Page


def _cb(action: ClientsAction, client_id: int = 0, page: int = 0) -> ClientsCb:
    return ClientsCb(action=action, client_id=client_id, page=page)


def _client_rows(clients: list[Client]) -> list[list]:
    return [[button(client.name, _cb(ClientsAction.OPEN, client.id))] for client in clients]


def clients_list(page: Page[Client]) -> InlineKeyboardMarkup:
    return markup(
        *_client_rows(page.items),
        pager(page, lambda number: _cb(ClientsAction.LIST, page=number)),
        [
            button(texts.BTN_FIND, _cb(ClientsAction.SEARCH)),
            button(texts.BTN_ADD, _cb(ClientsAction.ADD)),
        ],
        [home_button()],
    )


def back_to_list() -> InlineKeyboardMarkup:
    return markup([button(texts.BTN_BACK, _cb(ClientsAction.LIST)), home_button()])


def search_results(page: Page[Client]) -> InlineKeyboardMarkup:
    return markup(
        *_client_rows(page.items),
        pager(page, lambda number: _cb(ClientsAction.RESULTS, page=number)),
        [button(texts.BTN_BACK, _cb(ClientsAction.LIST)), home_button()],
    )


def ask_comment() -> InlineKeyboardMarkup:
    return markup(
        [button(texts.BTN_SKIP, _cb(ClientsAction.SKIP_COMMENT))],
        [button(texts.BTN_BACK, _cb(ClientsAction.BACK_TO_NAME)), home_button()],
    )


def open_client(client_id: int) -> InlineKeyboardMarkup:
    return markup([button(texts.BTN_OPEN_CLIENT, _cb(ClientsAction.OPEN, client_id))])


def client_card(client: Client, can_delete: bool) -> InlineKeyboardMarkup:
    delete_row = (
        [button(texts.BTN_DELETE, _cb(ClientsAction.DELETE, client.id))] if can_delete else []
    )
    return markup(
        [button(texts.BTN_HISTORY, _cb(ClientsAction.HISTORY, client.id))],
        [button(texts.BTN_STATEMENT, _cb(ClientsAction.STATEMENT, client.id))],
        [button(texts.BTN_EDIT, _cb(ClientsAction.EDIT, client.id))],
        delete_row,
        [button(texts.BTN_ALL_CLIENTS, _cb(ClientsAction.LIST)), home_button()],
    )


def edit_menu(client_id: int) -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_EDIT_NAME, _cb(ClientsAction.EDIT_NAME, client_id)),
            button(texts.BTN_EDIT_COMMENT, _cb(ClientsAction.EDIT_COMMENT, client_id)),
        ],
        [button(texts.BTN_BACK, _cb(ClientsAction.OPEN, client_id)), home_button()],
    )


def back_to_edit(client_id: int) -> InlineKeyboardMarkup:
    return markup([button(texts.BTN_BACK, _cb(ClientsAction.EDIT, client_id)), home_button()])


def edit_comment(client_id: int, has_comment: bool) -> InlineKeyboardMarkup:
    clear_row = (
        [button(texts.BTN_CLEAR_COMMENT, _cb(ClientsAction.CLEAR_COMMENT, client_id))]
        if has_comment
        else []
    )
    return markup(
        clear_row,
        [button(texts.BTN_BACK, _cb(ClientsAction.EDIT, client_id)), home_button()],
    )


def confirm_delete(client_id: int) -> InlineKeyboardMarkup:
    return markup(
        [button(texts.BTN_CONFIRM_DELETE, _cb(ClientsAction.CONFIRM_DELETE, client_id))],
        [button(texts.BTN_BACK, _cb(ClientsAction.OPEN, client_id)), home_button()],
    )
