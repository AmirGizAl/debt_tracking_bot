import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.domain.currency import Currency
from app.domain.errors import InvalidConversion, InvalidNumber, InvalidOperationData
from app.domain.operations import (
    OperationDraft,
    OperationType,
    RepayWarning,
    WarningKind,
    compute_terms,
    deltas,
    repay_warning,
)

LEND, REPAY_IN, BORROW, REPAY_OUT = (
    OperationType.LEND,
    OperationType.REPAY_IN,
    OperationType.BORROW,
    OperationType.REPAY_OUT,
)
D = Decimal


@pytest.mark.parametrize(
    ("op_type", "expected"),
    [
        (LEND, (D("600"), D("-52500"))),
        (REPAY_IN, (D("-600"), D("52500"))),
        (BORROW, (D("-600"), D("52500"))),
        (REPAY_OUT, (D("600"), D("-52500"))),
    ],
)
def test_deltas_by_type(op_type: OperationType, expected: tuple[Decimal, Decimal]) -> None:
    # TZ 7.1: debt_delta applies to the debt currency, cash_delta to the cash currency.
    assert deltas(op_type, D("600"), D("52500")) == expected


@pytest.mark.parametrize("op_type", list(OperationType))
def test_reversal_mirrors_deltas(op_type: OperationType) -> None:
    debt, cash = deltas(op_type, D("100"), D("8750"))
    assert deltas(op_type, D("100"), D("8750"), reversal=True) == (-debt, -cash)


@pytest.mark.parametrize(
    ("op_type", "balance", "amount", "expected"),
    [
        (REPAY_IN, "0", "100", RepayWarning(WarningKind.NOTHING_OWED_TO_YOU)),
        (REPAY_IN, "-50", "100", RepayWarning(WarningKind.NOTHING_OWED_TO_YOU)),
        (REPAY_IN, "100", "150", RepayWarning(WarningKind.OVERPAID_TO_YOU, D("50"))),
        (REPAY_IN, "600", "600", None),
        (REPAY_IN, "600", "400", None),
        (REPAY_OUT, "0", "100", RepayWarning(WarningKind.NOTHING_YOU_OWE)),
        (REPAY_OUT, "50", "100", RepayWarning(WarningKind.NOTHING_YOU_OWE)),
        (REPAY_OUT, "-30000", "40000", RepayWarning(WarningKind.OVERPAID_BY_YOU, D("10000"))),
        (REPAY_OUT, "-30000", "27000", None),
        (REPAY_OUT, "-30000", "30000", None),
        (LEND, "0", "100", None),
        (BORROW, "0", "100", None),
    ],
)
def test_repay_warnings(
    op_type: OperationType, balance: str, amount: str, expected: RepayWarning | None
) -> None:
    assert repay_warning(op_type, D(balance), D(amount)) == expected


def draft(**overrides: object) -> OperationDraft:
    fields: dict[str, object] = {
        "request_id": uuid.uuid4(),
        "type": REPAY_IN,
        "client_id": 1,
        "debt_currency": Currency.USD,
        "cash_currency": Currency.USD,
        "cash_amount": D("400"),
        "op_date": date(2026, 9, 10),
    }
    fields.update(overrides)
    return OperationDraft(**fields)  # type: ignore[arg-type]


def test_terms_same_currency() -> None:
    terms = compute_terms(draft())

    assert terms.debt_amount == D("400")
    assert (terms.debt_delta, terms.cash_delta) == (D("-400"), D("400"))
    assert terms.rate is terms.rate_base is terms.rate_quote is None


def test_terms_other_currency_derive_debt_amount() -> None:
    terms = compute_terms(draft(cash_currency=Currency.KGS, cash_amount=D("52500"), rate=D("87.5")))

    assert terms.debt_amount == D("600.00")
    assert (terms.rate_base, terms.rate_quote) == (Currency.USD, Currency.KGS)
    assert (terms.debt_delta, terms.cash_delta) == (D("-600.00"), D("52500"))


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"type": LEND, "cash_currency": Currency.KGS, "rate": D("87.5")}, InvalidOperationData),
        ({"cash_currency": Currency.KGS}, InvalidOperationData),
        ({"rate": D("1")}, InvalidOperationData),
        ({"cash_amount": D("0")}, InvalidNumber),
        ({"cash_amount": D("1.005")}, InvalidNumber),
        ({"cash_amount": D("1000000000000")}, InvalidNumber),
        (
            {"cash_currency": Currency.KGS, "cash_amount": D("0.01"), "rate": D("87.5")},
            InvalidConversion,
        ),
    ],
)
def test_invalid_drafts(overrides: dict[str, object], error: type[Exception]) -> None:
    with pytest.raises(error):
        compute_terms(draft(**overrides))
