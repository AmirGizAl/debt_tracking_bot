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


class BalancesAction(StrEnum):
    SHOW = "show"
    RECORDS = "rec"
    ADJUST = "adj"


class BalancesCb(CallbackData, prefix="b"):
    action: BalancesAction
    page: int = 0


class OpeningAction(StrEnum):
    SHOW = "show"
    ENTER = "enter"
    CURRENCY = "cur"
    SAVE = "save"
    DONT_SAVE = "no"
    BACK = "back"


class OpeningCb(CallbackData, prefix="ob"):
    """Opening balances in the settings; steps work on the current screen only."""

    action: OpeningAction
    value: str = ""


class ExchangeAction(StrEnum):
    GIVE = "give"  # value: currency
    GET = "get"  # value: currency
    SWITCH_SIDE = "side"  # type the amount the client gets instead
    LAST_RATE = "rate"
    MODE = "mode"  # value: ExchangeMode
    SAVE = "save"
    DONT_SAVE = "no"
    EDIT_AMOUNT = "amt"
    COMMENT = "cmt"
    SET_CLIENT = "cli"
    BACK = "back"


class ExchangeCb(CallbackData, prefix="x"):
    """Steps of the exchange scenario; valid only on the current scenario screen."""

    action: ExchangeAction
    value: str = ""


class PickAction(StrEnum):
    CLIENT = "cl"  # value: client id
    SEARCH = "sr"
    RESULTS = "rs"  # value: page
    NEW = "nc"
    SKIP_COMMENT = "skc"
    BACK = "back"


class PickCb(CallbackData, prefix="cp"):
    """Choosing a client inside a scenario (exchange, som loans, statements)."""

    action: PickAction
    value: str = ""
