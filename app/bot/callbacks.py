"""CallbackData factories. Prefixes are short: Telegram limits callback data to 64 bytes.

Old messages keep their buttons. Prefixes of version 1 scenarios (o, r, k, aj, rv, h, rp) are
retired and must not be reused: a v1 button "Открыть запись №3" must not open the unrelated
record №3 of version 2 (record numbers start again from 1).
"""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class MenuAction(StrEnum):
    HOME = "home"
    EXCHANGE = "ex"
    TO_PAY = "pay"  # «Ждут выдачи»
    TO_RECEIVE = "recv"  # «Ждут оплаты»
    LOANS = "loans"
    CLIENTS = "cl"
    BALANCES = "bal"
    REPORTS = "rep"
    CLOSE_DAY = "close"
    SETTINGS = "set"


class MenuCb(CallbackData, prefix="m"):
    action: MenuAction


class NoopCb(CallbackData, prefix="noop"):
    """Buttons that only display information (e.g. a page counter)."""


class SettingsAction(StrEnum):
    HOME = "home"
    HELPERS = "list"
    ADD = "add"
    OPEN = "open"
    DELETE = "del"
    CONFIRM_DELETE = "delok"


class SettingsCb(CallbackData, prefix="s"):
    action: SettingsAction
    helper_id: int = 0


class ClientsAction(StrEnum):
    LIST = "ls"
    OPEN = "op"
    SEARCH = "sr"
    RESULTS = "rs"
    ADD = "ad"
    SKIP_COMMENT = "sk"
    BACK_TO_NAME = "bn"
    EDIT = "ed"
    EDIT_NAME = "en"
    EDIT_COMMENT = "ec"
    CLEAR_COMMENT = "cc"
    DELETE = "dl"
    CONFIRM_DELETE = "dk"


class ClientsCb(CallbackData, prefix="c"):
    action: ClientsAction
    client_id: int = 0
    page: int = 0
