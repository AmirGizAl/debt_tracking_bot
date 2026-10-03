from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import DayAction, DayCb
from app.bot.keyboards.common import button, home_button, markup
from app.services.reports.data import ReportFormat


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, DayCb(action=DayAction.BACK)), home_button()]


def rate_step(previous_label: str | None) -> InlineKeyboardMarkup:
    """«Как в прошлый раз: 87,65» when the last closed day had this rate (TZ 8.2)."""
    previous = [button(previous_label, DayCb(action=DayAction.LAST_RATE))] if previous_label else []
    return markup(previous, _back_row())


def preliminary(with_rates: bool) -> InlineKeyboardMarkup:
    """TZ 13.9: the numbers in the chat, then «Excel» or «PDF»."""
    return markup(
        [
            button(texts.BTN_EXCEL, DayCb(action=DayAction.FILE, fmt=ReportFormat.XLSX)),
            button(texts.BTN_PDF, DayCb(action=DayAction.FILE, fmt=ReportFormat.PDF)),
        ],
        [button(texts.BTN_CHANGE_RATES, DayCb(action=DayAction.CHANGE_RATES))]
        if with_rates
        else [],
        _back_row(),
    )


def closing(day_number: int, with_rates: bool) -> InlineKeyboardMarkup:
    """TZ 7.2 step 3: «Закрыть день №N», «Изменить курсы», «Не закрывать»."""
    return markup(
        [button(texts.btn_close_day(day_number), DayCb(action=DayAction.CLOSE))],
        [button(texts.BTN_CHANGE_RATES, DayCb(action=DayAction.CHANGE_RATES))]
        if with_rates
        else [],
        [button(texts.BTN_DONT_CLOSE, DayCb(action=DayAction.DONT_CLOSE))],
    )
