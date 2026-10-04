"""Operation types and the entries they post (TZ 6.3, 6.4). Pure functions, no database.

Every record is a row in `operations` plus one or more entries: an entry changes either a
balance (`cash`) or the obligation of a client in one of two books. Balances and obligations
are never stored, they are sums of entries. An obligation above zero means the client owes
the exchange office, below zero the office owes the client.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from app.domain.currency import HOME_CURRENCY, Currency
from app.domain.errors import ClientRequired, InvalidOperationData, NothingToExchange
from app.domain.money import MAX_AMOUNT
from app.domain.rates import rate_pair


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
    # Debts from before the bot (agreed on 03.10.2026): an obligation without money.
    OPENING_DEBT = "opening_debt"  # book `exchange`, any currency
    OPENING_LOAN = "opening_loan"  # book `loan`, KGS


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
OPENING_DEBT_TYPES = frozenset({OperationType.OPENING_DEBT, OperationType.OPENING_LOAN})
OPENING_DEBT_TYPE = {
    Book.EXCHANGE: OperationType.OPENING_DEBT,
    Book.LOAN: OperationType.OPENING_LOAN,
}

# Sign of the obligation change; the balance moves the other way (TZ 6.3).
OBLIGATION_SIGN = {
    OperationType.EXCHANGE_PAYOUT: 1,
    OperationType.EXCHANGE_RECEIPT: -1,
    OperationType.LOAN_GIVE: 1,
    OperationType.LOAN_REPAY_IN: -1,
    OperationType.LOAN_TAKE: -1,
    OperationType.LOAN_REPAY_OUT: 1,
}


@dataclass(frozen=True)
class Entry:
    kind: EntryKind
    currency: Currency
    delta: Decimal
    book: Book | None = None
    client_id: int | None = None

    def reversed(self) -> "Entry":
        return replace(self, delta=-self.delta)


def cash(currency: Currency, delta: Decimal) -> Entry:
    return Entry(EntryKind.CASH, currency, delta)


def obligation(client_id: int, book: Book, currency: Currency, delta: Decimal) -> Entry:
    return Entry(EntryKind.OBLIGATION, currency, delta, book, client_id)


@dataclass(frozen=True)
class Draft:
    """A record before it is saved: the fields of `operations` and its entries."""

    type: OperationType
    entries: tuple[Entry, ...]
    client_id: int | None = None
    currency: Currency | None = None
    amount: Decimal | None = None
    give_currency: Currency | None = None
    give_amount: Decimal | None = None
    get_currency: Currency | None = None
    get_amount: Decimal | None = None
    rate: Decimal | None = None
    rate_base: Currency | None = None
    rate_quote: Currency | None = None
    received_now: bool | None = None
    paid_now: bool | None = None
    comment: str | None = None
    reason: str | None = None


def cash_changes(entries: tuple[Entry, ...] | list[Entry]) -> dict[Currency, Decimal]:
    """Net change of every balance the entries touch."""
    changes: dict[Currency, Decimal] = defaultdict(Decimal)
    for entry in entries:
        if entry.kind == EntryKind.CASH:
            changes[entry.currency] += entry.delta
    return dict(changes)


def _check_amount(amount: Decimal) -> None:
    if not 0 < amount <= MAX_AMOUNT:
        raise InvalidOperationData(f"amount out of range: {amount}")


@dataclass(frozen=True)
class ExchangeTerms:
    """What the client gives and gets, and whether each side happens now (TZ 6.4)."""

    give_currency: Currency
    give_amount: Decimal
    get_currency: Currency
    get_amount: Decimal
    received_now: bool
    paid_now: bool
    rate: Decimal | None = None

    @property
    def instant(self) -> bool:
        return self.received_now and self.paid_now


def exchange_cash_changes(terms: ExchangeTerms) -> dict[Currency, Decimal]:
    """How the balances move, known before the client is chosen (early check, TZ 13.3)."""
    changes: dict[Currency, Decimal] = defaultdict(Decimal)
    if terms.received_now:
        changes[terms.give_currency] += terms.give_amount
    if terms.paid_now:
        changes[terms.get_currency] -= terms.get_amount
    return dict(changes)


def exchange_draft(
    terms: ExchangeTerms, client_id: int | None, comment: str | None = None
) -> Draft:
    if not terms.instant and client_id is None:
        raise ClientRequired()
    _check_amount(terms.give_amount)
    _check_amount(terms.get_amount)
    rate_base = rate_quote = None
    if terms.give_currency == terms.get_currency:
        # A transfer without conversion: no rate, the difference is the commission.
        if terms.rate is not None:
            raise InvalidOperationData("a transfer in one currency has no rate")
        if terms.give_amount == terms.get_amount and terms.instant:
            raise NothingToExchange()
    else:
        if terms.rate is None or terms.rate <= 0:
            raise InvalidOperationData("an exchange of two currencies needs a rate")
        rate_base, rate_quote = rate_pair(terms.give_currency, terms.get_currency)
    entries: list[Entry] = []
    if terms.received_now:
        entries.append(cash(terms.give_currency, terms.give_amount))
    else:
        assert client_id is not None
        entries.append(obligation(client_id, Book.EXCHANGE, terms.give_currency, terms.give_amount))
    if terms.paid_now:
        entries.append(cash(terms.get_currency, -terms.get_amount))
    else:
        assert client_id is not None
        entries.append(obligation(client_id, Book.EXCHANGE, terms.get_currency, -terms.get_amount))
    return Draft(
        type=OperationType.EXCHANGE,
        entries=tuple(entries),
        client_id=client_id,
        give_currency=terms.give_currency,
        give_amount=terms.give_amount,
        get_currency=terms.get_currency,
        get_amount=terms.get_amount,
        rate=terms.rate if rate_base is not None else None,
        rate_base=rate_base,
        rate_quote=rate_quote,
        received_now=terms.received_now,
        paid_now=terms.paid_now,
        comment=comment,
    )


def _client_amount_draft(
    op_type: OperationType,
    book: Book,
    client_id: int | None,
    currency: Currency,
    amount: Decimal,
    comment: str | None,
) -> Draft:
    if client_id is None:
        raise ClientRequired()
    _check_amount(amount)
    sign = OBLIGATION_SIGN[op_type]
    return Draft(
        type=op_type,
        entries=(
            cash(currency, -sign * amount),
            obligation(client_id, book, currency, sign * amount),
        ),
        client_id=client_id,
        currency=currency,
        amount=amount,
        comment=comment,
    )


def settlement_draft(
    op_type: OperationType,
    client_id: int | None,
    currency: Currency,
    amount: Decimal,
    comment: str | None = None,
) -> Draft:
    """Payout or receipt of an exchange obligation (TZ 13.4)."""
    if op_type not in SETTLEMENT_TYPES:
        raise InvalidOperationData(f"not a settlement: {op_type}")
    return _client_amount_draft(op_type, Book.EXCHANGE, client_id, currency, amount, comment)


def loan_draft(
    op_type: OperationType, client_id: int | None, amount: Decimal, comment: str | None = None
) -> Draft:
    """One of the four som loan records (TZ 13.5); always KGS."""
    if op_type not in LOAN_TYPES:
        raise InvalidOperationData(f"not a loan record: {op_type}")
    return _client_amount_draft(op_type, Book.LOAN, client_id, HOME_CURRENCY, amount, comment)


def adjustment_draft(currency: Currency, amount: Decimal, reason: str) -> Draft:
    """A signed correction of a balance after counting the money (TZ 10)."""
    if amount == 0:
        raise InvalidOperationData("an adjustment changes the balance")
    _check_amount(abs(amount))
    return Draft(
        type=OperationType.ADJUSTMENT,
        entries=(cash(currency, amount),),
        currency=currency,
        amount=amount,
        reason=reason,
    )


def opening_draft(currency: Currency, amount: Decimal) -> Draft:
    """An opening balance, entered before the first closing of a day (TZ 9)."""
    _check_amount(amount)
    return Draft(
        type=OperationType.OPENING,
        entries=(cash(currency, amount),),
        currency=currency,
        amount=amount,
    )


def opening_debt_draft(
    client_id: int | None, book: Book, currency: Currency, amount: Decimal
) -> Draft:
    """A debt from before the bot (agreed on 03.10.2026): only the obligation, no money moves.

    `amount` is signed like an obligation: above zero the client owes us.
    """
    if client_id is None:
        raise ClientRequired()
    if amount == 0:
        raise InvalidOperationData("an opening debt is not zero")
    _check_amount(abs(amount))
    if book == Book.LOAN and currency != HOME_CURRENCY:
        raise InvalidOperationData("som loans are in KGS only")
    return Draft(
        type=OPENING_DEBT_TYPE[book],
        entries=(obligation(client_id, book, currency, amount),),
        client_id=client_id,
        currency=currency,
        amount=amount,
    )
