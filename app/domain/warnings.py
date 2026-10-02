"""Warnings on the confirmation screen (TZ 6.6). They never forbid a record.

`balance` is the client's current obligation in the book and currency of the record (above
zero the client owes us), `amount` is the amount of the record.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domain.entries import OBLIGATION_SIGN, OperationType


class WarningKind(StrEnum):
    NOTHING_WE_OWE = "nothing_we_owe"  # we pay out, but owe the client nothing
    MORE_THAN_WE_OWE = "more_than_we_owe"
    NOTHING_OWED_TO_US = "nothing_owed_to_us"  # we take money, but the client owes nothing
    MORE_THAN_OWED = "more_than_owed"


@dataclass(frozen=True)
class RecordWarning:
    kind: WarningKind
    excess: Decimal | None = None  # the part that turns into a debt the other way


# Records that pay money out against an obligation and records that take money in.
PAYING_OUT = frozenset({OperationType.EXCHANGE_PAYOUT, OperationType.LOAN_REPAY_OUT})
TAKING_IN = frozenset({OperationType.EXCHANGE_RECEIPT, OperationType.LOAN_REPAY_IN})


def settlement_warning(
    op_type: OperationType, balance: Decimal, amount: Decimal
) -> RecordWarning | None:
    """For payouts, receipts, «Мне вернули» and «Я вернул»; other records have none."""
    if op_type in PAYING_OUT:
        assert OBLIGATION_SIGN[op_type] > 0
        if balance >= 0:
            return RecordWarning(WarningKind.NOTHING_WE_OWE)
        if -balance < amount:
            return RecordWarning(WarningKind.MORE_THAN_WE_OWE, amount + balance)
    elif op_type in TAKING_IN:
        if balance <= 0:
            return RecordWarning(WarningKind.NOTHING_OWED_TO_US)
        if balance < amount:
            return RecordWarning(WarningKind.MORE_THAN_OWED, amount - balance)
    return None
