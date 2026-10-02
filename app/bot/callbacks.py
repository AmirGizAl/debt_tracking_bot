"""CallbackData factories. Prefixes are short: Telegram limits callback data to 64 bytes.

Old messages keep their buttons. Prefixes of version 1 scenarios (o, r, k, aj, rv, h, rp) are
retired and must not be reused: a v1 button "Открыть запись №3" must not open the unrelated
record №3 of version 2 (record numbers start again from 1).
"""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData

from app.domain.currency import Currency
from app.domain.entries import OperationType


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
    HISTORY = "hs"  # «История записей» (same value as in version 1: same meaning)
    STATEMENT = "st"  # «Выписка»


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


class WaitingCb(CallbackData, prefix="w"):
    """A page of «Ждут выдачи» (`paying`) or «Ждут оплаты»; a view, always valid."""

    paying: bool
    page: int = 0


class SettleAction(StrEnum):
    START = "go"  # a row of a waiting list: client, currency, paying, page of the list
    FROM_CARD = "card"  # «Выдать» / «Получить» on the client card: client, paying
    CURRENCY = "cur"  # currency
    WHOLE = "all"  # «Всю сумму»
    SAVE = "save"
    DONT_SAVE = "no"
    BACK = "back"


class SettleCb(CallbackData, prefix="st"):
    """Payouts and receipts of exchange obligations (TZ 13.4).

    START and FROM_CARD begin a scenario from a view; the other steps are valid only on the
    current scenario screen.
    """

    action: SettleAction
    paying: bool = True
    client_id: int = 0
    currency: Currency | None = None
    page: int = 0


class LoansAction(StrEnum):
    SHOW = "show"
    START = "go"  # op_type
    WHO_OWES = "who"  # page
    WHOLE = "all"  # «Всю сумму»
    SKIP_COMMENT = "skip"
    SAVE = "save"
    DONT_SAVE = "no"
    BACK = "back"


class LoansCb(CallbackData, prefix="ln"):
    """«Долги в сомах» (TZ 13.5); scenario steps are valid only on the current screen."""

    action: LoansAction
    op_type: OperationType | None = None
    page: int = 0
