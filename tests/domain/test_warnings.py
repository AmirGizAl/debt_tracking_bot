"""Warnings of the confirmation screen (TZ 6.6)."""

from decimal import Decimal

import pytest

from app.domain.entries import OperationType
from app.domain.warnings import (
    RecordWarning,
    WarningKind,
    settlement_warning,
    settling_amount,
)

D = Decimal
PAYOUT, RECEIPT = OperationType.EXCHANGE_PAYOUT, OperationType.EXCHANGE_RECEIPT
REPAY_OUT, REPAY_IN = OperationType.LOAN_REPAY_OUT, OperationType.LOAN_REPAY_IN


@pytest.mark.parametrize(
    ("op_type", "balance", "amount", "expected"),
    [
        # We owe 1 000 and pay 1 000 or less: fine.
        (PAYOUT, "-1000", "1000", None),
        (PAYOUT, "-1000", "400", None),
        (PAYOUT, "0", "100", RecordWarning(WarningKind.NOTHING_WE_OWE)),
        (PAYOUT, "50", "100", RecordWarning(WarningKind.NOTHING_WE_OWE)),
        (PAYOUT, "-600", "1000", RecordWarning(WarningKind.MORE_THAN_WE_OWE, D("400"))),
        (RECEIPT, "1000", "1000", None),
        (RECEIPT, "0", "100", RecordWarning(WarningKind.NOTHING_OWED_TO_US)),
        (RECEIPT, "-5", "100", RecordWarning(WarningKind.NOTHING_OWED_TO_US)),
        (RECEIPT, "100", "150", RecordWarning(WarningKind.MORE_THAN_OWED, D("50"))),
        # «Я вернул» and «Мне вернули» follow the same four rules in the loan book.
        (REPAY_OUT, "-50000", "50000", None),
        (REPAY_OUT, "0", "1", RecordWarning(WarningKind.NOTHING_WE_OWE)),
        (REPAY_OUT, "-30", "50", RecordWarning(WarningKind.MORE_THAN_WE_OWE, D("20"))),
        (REPAY_IN, "50000", "5000", None),
        (REPAY_IN, "-1", "1", RecordWarning(WarningKind.NOTHING_OWED_TO_US)),
        (REPAY_IN, "40", "50", RecordWarning(WarningKind.MORE_THAN_OWED, D("10"))),
    ],
)
def test_settlement_warnings(
    op_type: OperationType, balance: str, amount: str, expected: RecordWarning | None
) -> None:
    assert settlement_warning(op_type, D(balance), D(amount)) == expected


@pytest.mark.parametrize(
    "op_type",
    [
        OperationType.LOAN_GIVE,
        OperationType.LOAN_TAKE,
        OperationType.EXCHANGE,
        OperationType.OPENING,
    ],
)
def test_other_records_have_no_warnings(op_type: OperationType) -> None:
    assert settlement_warning(op_type, D("0"), D("100")) is None


@pytest.mark.parametrize(
    ("op_type", "balance", "expected"),
    [
        (PAYOUT, "-1000", "1000"),  # «Всю сумму: 1 000 USD»
        (PAYOUT, "0", None),
        (PAYOUT, "250", None),  # the client owes us: nothing to pay out
        (RECEIPT, "5000", "5000"),
        (RECEIPT, "-5000", None),
        (REPAY_IN, "50000", "50000"),
        (REPAY_IN, "0", None),
        (REPAY_OUT, "-700", "700"),
        (REPAY_OUT, "700", None),
        (OperationType.LOAN_GIVE, "-700", None),  # only records that settle a debt
        (OperationType.LOAN_TAKE, "700", None),
    ],
)
def test_settling_amount(op_type: OperationType, balance: str, expected: str | None) -> None:
    result = settling_amount(op_type, D(balance))

    assert result == (D(expected) if expected is not None else None)
