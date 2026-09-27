"""Record rules: how each type moves the client's debt and the cash (TZ 7.1, 7.5)."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.domain.currency import Currency
from app.domain.errors import InvalidNumber, InvalidOperationData, NumberProblem
from app.domain.money import MAX_AMOUNT, quantize_money
from app.domain.rates import convert_payment, rate_pair


class OperationType(StrEnum):
    LEND = "lend"  # Выдал в долг
    REPAY_IN = "repay_in"  # Мне вернули
    BORROW = "borrow"  # Взял в долг
    REPAY_OUT = "repay_out"  # Я вернул


NEW_DEBT_TYPES = frozenset({OperationType.LEND, OperationType.BORROW})
REPAY_TYPES = frozenset({OperationType.REPAY_IN, OperationType.REPAY_OUT})

# +1: the client owes the owner more (and cash goes out); -1: the opposite.
_DEBT_SIGN = {
    OperationType.LEND: 1,
    OperationType.REPAY_IN: -1,
    OperationType.BORROW: -1,
    OperationType.REPAY_OUT: 1,
}


def deltas(
    op_type: OperationType, debt_amount: Decimal, cash_amount: Decimal, reversal: bool = False
) -> tuple[Decimal, Decimal]:
    """(debt_delta, cash_delta) of a record; a reversal mirrors the original."""
    sign = _DEBT_SIGN[op_type] * (-1 if reversal else 1)
    return sign * debt_amount, -sign * cash_amount


def takes_cash(op_type: OperationType) -> bool:
    """Lend and repay_out take money out of the cash (their reversals bring it back)."""
    return _DEBT_SIGN[op_type] > 0


class WarningKind(StrEnum):
    NOTHING_OWED_TO_YOU = "nothing_owed_to_you"
    OVERPAID_TO_YOU = "overpaid_to_you"
    NOTHING_YOU_OWE = "nothing_you_owe"
    OVERPAID_BY_YOU = "overpaid_by_you"


@dataclass(frozen=True)
class RepayWarning:
    kind: WarningKind
    excess: Decimal | None = None


def repay_warning(op_type: OperationType, balance: Decimal, amount: Decimal) -> RepayWarning | None:
    """Warning for the confirmation screen (TZ 7.5).

    `balance` is the client's current balance in the debt currency, `amount` is what the
    record takes off the debt. Warnings never forbid the record.
    """
    if op_type == OperationType.REPAY_IN:
        if balance <= 0:
            return RepayWarning(WarningKind.NOTHING_OWED_TO_YOU)
        if balance < amount:
            return RepayWarning(WarningKind.OVERPAID_TO_YOU, amount - balance)
    elif op_type == OperationType.REPAY_OUT:
        if balance >= 0:
            return RepayWarning(WarningKind.NOTHING_YOU_OWE)
        if -balance < amount:
            return RepayWarning(WarningKind.OVERPAID_BY_YOU, amount - (-balance))
    return None


@dataclass(frozen=True)
class OperationDraft:
    """What the user entered. The debt amount is always derived, never trusted."""

    request_id: uuid.UUID
    type: OperationType
    client_id: int
    debt_currency: Currency
    cash_currency: Currency
    cash_amount: Decimal
    op_date: date
    rate: Decimal | None = None
    comment: str | None = None


@dataclass(frozen=True)
class OperationTerms:
    debt_amount: Decimal
    cash_amount: Decimal
    rate: Decimal | None
    rate_base: Currency | None
    rate_quote: Currency | None
    debt_delta: Decimal
    cash_delta: Decimal


def compute_terms(draft: OperationDraft) -> OperationTerms:
    """Validate a draft and derive amounts and deltas (TZ 4.6, 6.3, 7.1)."""
    cash_amount = draft.cash_amount
    if cash_amount != quantize_money(cash_amount):
        raise InvalidNumber(NumberProblem.PRECISION)
    if cash_amount <= 0:
        raise InvalidNumber(NumberProblem.NOT_POSITIVE)
    if cash_amount > MAX_AMOUNT:
        raise InvalidNumber(NumberProblem.TOO_LARGE)

    if draft.debt_currency == draft.cash_currency:
        if draft.rate is not None:
            raise InvalidOperationData("a rate is only for payments in another currency")
        debt_amount = cash_amount
        rate = rate_base = rate_quote = None
    else:
        if draft.type in NEW_DEBT_TYPES:
            raise InvalidOperationData("a new debt is always in one currency")
        if draft.rate is None or draft.rate <= 0:
            raise InvalidOperationData("a payment in another currency needs a positive rate")
        rate = draft.rate
        rate_base, rate_quote = rate_pair(draft.debt_currency, draft.cash_currency)
        debt_amount = convert_payment(cash_amount, draft.cash_currency, draft.debt_currency, rate)

    debt_delta, cash_delta = deltas(draft.type, debt_amount, cash_amount)
    return OperationTerms(
        debt_amount=debt_amount,
        cash_amount=cash_amount,
        rate=rate,
        rate_base=rate_base,
        rate_quote=rate_quote,
        debt_delta=debt_delta,
        cash_delta=cash_delta,
    )
