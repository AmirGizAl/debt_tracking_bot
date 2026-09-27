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
