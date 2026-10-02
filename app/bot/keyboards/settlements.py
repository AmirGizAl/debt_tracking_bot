from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import SettleAction, SettleCb, WaitingCb
from app.bot.keyboards.common import button, home_button, markup, pager
from app.domain.currency import CURRENCIES, Currency
from app.services.ledger import ObligationLine
from app.services.pagination import Page


def _cb(action: SettleAction, currency: Currency | None = None) -> SettleCb:
    return SettleCb(action=action, currency=currency)


def _back_row() -> list[InlineKeyboardButton]:
    return [button(texts.BTN_BACK, _cb(SettleAction.BACK)), home_button()]


def waiting_list(paying: bool, page: Page[ObligationLine]) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                texts.waiting_button(line.client, abs(line.amount), line.currency),
                SettleCb(
                    action=SettleAction.START,
                    paying=paying,
                    client_id=line.client_id,
                    currency=line.currency,
                    page=page.page,
                ),
            )
        ]
        for line in page.items
    ]
    return markup(
        *rows,
        pager(page, lambda number: WaitingCb(paying=paying, page=number)),
        [home_button()],
    )


def card_buttons(client_id: int) -> list[InlineKeyboardButton]:
    """«Выдать» and «Получить» of the client card."""
    return [
        button(
            texts.BTN_GIVE_OUT,
            SettleCb(action=SettleAction.FROM_CARD, paying=True, client_id=client_id),
        ),
        button(
            texts.BTN_TAKE_IN,
            SettleCb(action=SettleAction.FROM_CARD, paying=False, client_id=client_id),
        ),
    ]


def currencies(obligations: dict[Currency, Decimal]) -> InlineKeyboardMarkup:
    """All five currencies, each with the client's current obligation in it."""
    return markup(
        *[
            [
                button(
                    texts.settle_currency_button(currency, obligations.get(currency, Decimal(0))),
                    _cb(SettleAction.CURRENCY, currency),
                )
            ]
            for currency in CURRENCIES
        ],
        _back_row(),
    )


def amount_step(whole_label: str | None) -> InlineKeyboardMarkup:
    whole = [button(whole_label, _cb(SettleAction.WHOLE))] if whole_label else []
    return markup(whole, _back_row())


def confirm() -> InlineKeyboardMarkup:
    return markup(
        [
            button(texts.BTN_SAVE, _cb(SettleAction.SAVE)),
            button(texts.BTN_DONT_SAVE, _cb(SettleAction.DONT_SAVE)),
        ],
        [button(texts.BTN_BACK, _cb(SettleAction.BACK))],
    )
