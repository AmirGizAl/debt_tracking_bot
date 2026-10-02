"""Lines about the balances and obligations a record touches: «После сохранения» on the
confirmation screens, «После отмены» and the group posts."""

from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.domain.currency import CURRENCIES, Currency
from app.domain.entries import Book, Draft, EntryKind
from app.services import ledger


class EntryLike(Protocol):
    """An entry of a draft or a saved entry: both have these fields."""

    @property
    def kind(self) -> EntryKind: ...
    @property
    def currency(self) -> Currency: ...
    @property
    def book(self) -> Book | None: ...
    @property
    def delta(self) -> Decimal: ...


async def state_lines(
    session: AsyncSession,
    entries: Iterable[EntryLike],
    client_id: int | None,
    client_name: str | None,
    *,
    pending: bool,
    obligations_first: bool = False,
) -> list[str]:
    """Every balance and obligation the entries touch, in the display order.

    `pending`: the entries are not saved yet, the lines show the values after them; otherwise
    the lines show the values as they are now.
    """
    cash: dict[Currency, Decimal] = {}
    moves: dict[tuple[Book, Currency], Decimal] = {}
    for entry in entries:
        if entry.kind == EntryKind.CASH:
            cash[entry.currency] = cash.get(entry.currency, Decimal(0)) + entry.delta
        else:
            assert entry.book is not None
            key = (entry.book, entry.currency)
            moves[key] = moves.get(key, Decimal(0)) + entry.delta
    balances = []
    for currency in sorted(cash, key=CURRENCIES.index):
        if pending and cash[currency] == 0:
            continue  # e.g. a transfer that is fully paid at once: nothing changes
        value = await ledger.balance(session, currency)
        balances.append(texts.balance_line(currency, value + cash[currency] if pending else value))
    obligations = []
    order = [(book, currency) for book in Book for currency in CURRENCIES]
    for book, currency in sorted(moves, key=order.index):
        assert client_id is not None and client_name is not None
        value = await ledger.obligation(session, client_id, book, currency)
        if pending:
            value += moves[book, currency]
        obligations.append(texts.obligation_line(client_name, book, currency, value))
    return [*obligations, *balances] if obligations_first else [*balances, *obligations]


async def after_lines(
    session: AsyncSession,
    draft: Draft,
    client_name: str | None,
    *,
    obligations_first: bool = False,
) -> list[str]:
    """«После сохранения»: the values as they will be after the record."""
    return await state_lines(
        session,
        draft.entries,
        draft.client_id,
        client_name,
        pending=True,
        obligations_first=obligations_first,
    )
