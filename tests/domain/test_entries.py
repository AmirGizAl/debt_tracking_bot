"""Entries of every operation type (TZ 6.3, 6.4)."""

from decimal import Decimal

import pytest

from app.domain.currency import Currency
from app.domain.entries import (
    Book,
    Entry,
    ExchangeTerms,
    OperationType,
    adjustment_draft,
    cash,
    cash_changes,
    exchange_draft,
    loan_draft,
    obligation,
    opening_debt_draft,
    opening_draft,
    settlement_draft,
)
from app.domain.errors import ClientRequired, InvalidOperationData, NothingToExchange

USD, EUR, RUB, KGS = Currency.USD, Currency.EUR, Currency.RUB, Currency.KGS
D = Decimal
AZAMAT = 7
EXCHANGE, LOAN = Book.EXCHANGE, Book.LOAN


def terms(received_now: bool, paid_now: bool, **fields: object) -> ExchangeTerms:
    """88 500 RUB from the client for 1 000 USD at 88,5 (TZ 17.1, scenario 4)."""
    values: dict[str, object] = {
        "give_currency": RUB,
        "give_amount": D("88500"),
        "get_currency": USD,
        "get_amount": D("1000"),
        "received_now": received_now,
        "paid_now": paid_now,
        "rate": D("88.5"),
    }
    values.update(fields)
    return ExchangeTerms(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("received_now", "paid_now", "expected"),
    [
        (True, True, (cash(RUB, D("88500")), cash(USD, D("-1000")))),
        (
            True,
            False,
            (cash(RUB, D("88500")), obligation(AZAMAT, EXCHANGE, USD, D("-1000"))),
        ),
        (
            False,
            True,
            (obligation(AZAMAT, EXCHANGE, RUB, D("88500")), cash(USD, D("-1000"))),
        ),
        (
            False,
            False,
            (
                obligation(AZAMAT, EXCHANGE, RUB, D("88500")),
                obligation(AZAMAT, EXCHANGE, USD, D("-1000")),
            ),
        ),
    ],
)
def test_exchange_entries(received_now: bool, paid_now: bool, expected: tuple[Entry, ...]) -> None:
    draft = exchange_draft(terms(received_now, paid_now), AZAMAT, "комментарий")

    assert draft.entries == expected
    assert (draft.type, draft.client_id, draft.comment) == (
        OperationType.EXCHANGE,
        AZAMAT,
        "комментарий",
    )
    assert (draft.rate, draft.rate_base, draft.rate_quote) == (D("88.5"), USD, RUB)
    assert (draft.received_now, draft.paid_now) == (received_now, paid_now)
    assert (draft.currency, draft.amount) == (None, None)


def test_instant_exchange_needs_no_client() -> None:
    draft = exchange_draft(
        terms(True, True, give_currency=USD, give_amount=D("1000"), get_currency=KGS,
              get_amount=D("87000"), rate=D("87")),
        None,
    )  # fmt: skip

    assert draft.client_id is None
    assert (draft.rate_base, draft.rate_quote) == (USD, KGS)
    assert cash_changes(draft.entries) == {USD: D("1000"), KGS: D("-87000")}


@pytest.mark.parametrize(
    ("received_now", "paid_now"), [(True, False), (False, True), (False, False)]
)
def test_deferred_exchange_needs_a_client(received_now: bool, paid_now: bool) -> None:
    with pytest.raises(ClientRequired):
        exchange_draft(terms(received_now, paid_now), None)


def test_transfer_in_one_currency_has_no_rate() -> None:
    # TZ 17.1, scenario 12: 100 000 RUB in, 99 000 RUB out later; the difference is commission.
    draft = exchange_draft(
        terms(True, False, give_currency=RUB, give_amount=D("100000"), get_currency=RUB,
              get_amount=D("99000"), rate=None),
        AZAMAT,
    )  # fmt: skip

    assert draft.entries == (
        cash(RUB, D("100000")),
        obligation(AZAMAT, EXCHANGE, RUB, D("-99000")),
    )
    assert (draft.rate, draft.rate_base, draft.rate_quote) == (None, None, None)


def test_same_currency_same_amount_now_records_nothing() -> None:
    same = {"give_currency": RUB, "get_currency": RUB, "get_amount": D("88500"), "rate": None}

    with pytest.raises(NothingToExchange):
        exchange_draft(terms(True, True, **same), None)
    # With a side later it is a real obligation and allowed.
    assert len(exchange_draft(terms(True, False, **same), AZAMAT).entries) == 2


@pytest.mark.parametrize(
    "fields",
    [
        {"rate": None},
        {"rate": D("0")},
        {"get_currency": RUB, "get_amount": D("100"), "rate": D("1")},  # a rate for a transfer
        {"give_amount": D("0")},
        {"get_amount": D("1000000000000")},
    ],
)
def test_broken_exchange_is_refused(fields: dict[str, object]) -> None:
    with pytest.raises(InvalidOperationData):
        exchange_draft(terms(True, True, **fields), AZAMAT)


@pytest.mark.parametrize(
    ("op_type", "cash_delta", "obligation_delta"),
    [
        (OperationType.EXCHANGE_PAYOUT, "-1000", "1000"),
        (OperationType.EXCHANGE_RECEIPT, "1000", "-1000"),
    ],
)
def test_settlement_entries(op_type: OperationType, cash_delta: str, obligation_delta: str) -> None:
    draft = settlement_draft(op_type, AZAMAT, USD, D("1000"))

    assert draft.entries == (
        cash(USD, D(cash_delta)),
        obligation(AZAMAT, EXCHANGE, USD, D(obligation_delta)),
    )
    assert (draft.currency, draft.amount, draft.client_id) == (USD, D("1000"), AZAMAT)


@pytest.mark.parametrize(
    ("op_type", "cash_delta", "obligation_delta"),
    [
        (OperationType.LOAN_GIVE, "-50000", "50000"),
        (OperationType.LOAN_REPAY_IN, "50000", "-50000"),
        (OperationType.LOAN_TAKE, "50000", "-50000"),
        (OperationType.LOAN_REPAY_OUT, "-50000", "50000"),
    ],
)
def test_loan_entries(op_type: OperationType, cash_delta: str, obligation_delta: str) -> None:
    draft = loan_draft(op_type, AZAMAT, D("50000"))

    assert draft.entries == (
        cash(KGS, D(cash_delta)),
        obligation(AZAMAT, LOAN, KGS, D(obligation_delta)),
    )
    assert draft.currency == KGS


def test_loans_and_settlements_need_a_client() -> None:
    with pytest.raises(ClientRequired):
        loan_draft(OperationType.LOAN_GIVE, None, D("1"))
    with pytest.raises(ClientRequired):
        settlement_draft(OperationType.EXCHANGE_PAYOUT, None, USD, D("1"))


def test_types_are_checked() -> None:
    with pytest.raises(InvalidOperationData):
        loan_draft(OperationType.EXCHANGE_PAYOUT, AZAMAT, D("1"))
    with pytest.raises(InvalidOperationData):
        settlement_draft(OperationType.LOAN_GIVE, AZAMAT, USD, D("1"))


@pytest.mark.parametrize("amount", ["500", "-500"])
def test_adjustment_entries(amount: str) -> None:
    draft = adjustment_draft(EUR, D(amount), "пересчёт")

    assert draft.entries == (cash(EUR, D(amount)),)
    assert (draft.type, draft.amount, draft.reason) == (
        OperationType.ADJUSTMENT,
        D(amount),
        "пересчёт",
    )


def test_zero_adjustment_is_refused() -> None:
    with pytest.raises(InvalidOperationData):
        adjustment_draft(EUR, D("0"), "ничего")


def test_opening_entries() -> None:
    draft = opening_draft(KGS, D("1000000"))

    assert draft.entries == (cash(KGS, D("1000000")),)
    assert (draft.type, draft.client_id) == (OperationType.OPENING, None)


def test_reversed_entry_flips_the_sign() -> None:
    entry = obligation(AZAMAT, EXCHANGE, USD, D("-1000"))

    assert entry.reversed() == obligation(AZAMAT, EXCHANGE, USD, D("1000"))


@pytest.mark.parametrize(
    ("book", "currency", "amount", "op_type"),
    [
        (EXCHANGE, USD, "-1000", OperationType.OPENING_DEBT),  # we owe Азамат 1 000 USD
        (EXCHANGE, KGS, "5000", OperationType.OPENING_DEBT),
        (LOAN, KGS, "50000", OperationType.OPENING_LOAN),
    ],
)
def test_opening_debt_moves_no_money(
    book: Book, currency: Currency, amount: str, op_type: OperationType
) -> None:
    # Agreed on 03.10.2026: only the obligation, the balances stay as they are.
    draft = opening_debt_draft(AZAMAT, book, currency, D(amount))

    assert draft.entries == (obligation(AZAMAT, book, currency, D(amount)),)
    assert cash_changes(draft.entries) == {}
    assert (draft.type, draft.client_id, draft.amount) == (op_type, AZAMAT, D(amount))


def test_broken_opening_debts_are_refused() -> None:
    with pytest.raises(ClientRequired):
        opening_debt_draft(None, EXCHANGE, USD, D("100"))
    with pytest.raises(InvalidOperationData):
        opening_debt_draft(AZAMAT, EXCHANGE, USD, D("0"))
    with pytest.raises(InvalidOperationData):
        opening_debt_draft(AZAMAT, LOAN, USD, D("100"))  # som loans are in KGS only
