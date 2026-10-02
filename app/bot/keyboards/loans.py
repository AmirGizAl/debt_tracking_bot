from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import LoansAction, LoansCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.domain.entries import OperationType
from app.services.pagination import Page


def _cb(action: LoansAction, op_type: OperationType | None = None, page: int = 0) -> LoansCb:
    return LoansCb(action=action, op_type=op_type, page=page)


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, _cb(LoansAction.BACK)), home_button()]


def _start(op_type: OperationType) -> InlineKeyboardButton:
    return button(texts.LOAN_LABEL[op_type], _cb(LoansAction.START, op_type))


def screen() -> InlineKeyboardMarkup:
    """TZ 13.5: four records and «Кто кому должен»."""
    return markup(
        [_start(OperationType.LOAN_GIVE), _start(OperationType.LOAN_REPAY_IN)],
        [_start(OperationType.LOAN_TAKE), _start(OperationType.LOAN_REPAY_OUT)],
        [button(texts.BTN_WHO_OWES, _cb(LoansAction.WHO_OWES))],
        [home_button()],
    )


def who_owes(page: Page[object]) -> InlineKeyboardMarkup:
    return markup(
        pager(page, lambda number: _cb(LoansAction.WHO_OWES, page=number)),
        [button(texts.BTN_BACK, _cb(LoansAction.SHOW)), home_button()],
    )


def amount_step(whole_label: str | None) -> InlineKeyboardMarkup:
    whole = [button(whole_label, _cb(LoansAction.WHOLE))] if whole_label else []
    return markup(whole, _back_row())


def comment_step() -> InlineKeyboardMarkup:
    return markup([button(texts.BTN_SKIP, _cb(LoansAction.SKIP_COMMENT))], _back_row())


def confirm() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_SAVE, _cb(LoansAction.SAVE)),
            button(texts.BTN_DONT_SAVE, _cb(LoansAction.DONT_SAVE)),
        ],
        [button(texts.BTN_BACK, _cb(LoansAction.BACK))],
    )
