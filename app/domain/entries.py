"""Operation types and the two kinds of entries they post (TZ 6).

Every record is a row in `operations` plus one or more entries: an entry changes either a
balance (`cash`) or the obligation of a client in one of two books. Balances and obligations
are never stored, they are sums of entries.
"""

from enum import StrEnum


class OperationType(StrEnum):
    EXCHANGE = "exchange"
    EXCHANGE_PAYOUT = "exchange_payout"
    EXCHANGE_RECEIPT = "exchange_receipt"
    LOAN_GIVE = "loan_give"
    LOAN_REPAY_IN = "loan_repay_in"
    LOAN_TAKE = "loan_take"
    LOAN_REPAY_OUT = "loan_repay_out"
    ADJUSTMENT = "adjustment"
    OPENING = "opening"


class EntryKind(StrEnum):
    CASH = "cash"
    OBLIGATION = "obligation"


class Book(StrEnum):
    """Obligations of exchanges (any currency) and som loans (KGS only) never net out."""

    EXCHANGE = "exchange"
    LOAN = "loan"


LOAN_TYPES = frozenset(
    {
        OperationType.LOAN_GIVE,
        OperationType.LOAN_REPAY_IN,
        OperationType.LOAN_TAKE,
        OperationType.LOAN_REPAY_OUT,
    }
)
SETTLEMENT_TYPES = frozenset({OperationType.EXCHANGE_PAYOUT, OperationType.EXCHANGE_RECEIPT})
