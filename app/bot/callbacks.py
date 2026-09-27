"""CallbackData factories. Prefixes are short: Telegram limits callback data to 64 bytes."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class MenuAction(StrEnum):
    HOME = "home"
    LEND = "lend"
    REPAY_IN = "rin"
    BORROW = "brw"
    REPAY_OUT = "rout"
    CLIENTS = "cl"
    CASH = "cash"
    REPORTS = "rep"
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
    HISTORY = "hs"
    STATEMENT = "st"


class ClientsCb(CallbackData, prefix="c"):
    action: ClientsAction
    client_id: int = 0
    page: int = 0


class OpAction(StrEnum):
    CLIENT = "cl"
    SEARCH = "sr"
    RESULTS = "rs"
    NEW_CLIENT = "nc"
    SKIP_CLIENT_COMMENT = "skc"
    CURRENCY = "cur"
    SAME_CURRENCY = "same"
    OTHER_CURRENCY = "oth"
    PAY_CURRENCY = "pc"
    TODAY = "td"
    YESTERDAY = "yd"
    OTHER_DATE = "od"
    SKIP_COMMENT = "sk"
    SAVE = "save"
    DONT_SAVE = "no"
    BACK = "back"


class OpCb(CallbackData, prefix="o"):
    """Steps of the record scenarios; valid only on the current scenario screen."""

    action: OpAction
    value: str = ""


class RecordAction(StrEnum):
    OPEN = "op"
    CLIENT = "cl"
    REVERSE = "rv"


class RecordCb(CallbackData, prefix="r"):
    """Record card: works from any message (results, history, notifications)."""

    action: RecordAction
    operation_id: int
