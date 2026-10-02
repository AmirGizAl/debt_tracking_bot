"""The journal (TZ 6.2, 6.5, 6.7, 7.3). Every record is written by `post`.

One short isolated transaction: the open day FOR SHARE (a closing waits for it) -> advisory
locks for every balance the record lowers, in the order of currencies -> idempotency by
request_id -> the record's own checks -> no balance below zero -> the row and its entries.
Balances and obligations are sums of entries; nothing is stored.
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.db.models import BusinessDay, Client, DayStatus, Operation, OperationEntry, User
from app.domain.currency import CURRENCIES, Currency
from app.domain.entries import Book, Draft, EntryKind, cash_changes
from app.domain.errors import (
    ClientNotFound,
    InsufficientBalance,
    OperationNotFound,
    PermissionDenied,
)
from app.services.transactions import isolated

LOCK_NAMESPACE = 7402  # pg_advisory_xact_lock(namespace, key): one key per balance
ZERO = Decimal("0.00")

Check = Callable[[AsyncSession], Awaitable[None]]


def ensure_active(actor: User) -> None:
    if not actor.is_active:
        raise PermissionDenied("inactive user")


async def lock_balances(tx: AsyncSession, currencies: Iterable[Currency]) -> None:
    """Locks in the order of currencies, so two records never wait for each other."""
    for currency in sorted(set(currencies), key=CURRENCIES.index):
        await tx.execute(
            select(func.pg_advisory_xact_lock(LOCK_NAMESPACE, CURRENCIES.index(currency)))
        )


async def balance(session: AsyncSession, currency: Currency) -> Decimal:
    total = await session.scalar(
        select(func.sum(OperationEntry.delta)).where(
            OperationEntry.kind == EntryKind.CASH, OperationEntry.currency == currency
        )
    )
    return total if total is not None else ZERO


async def balances(session: AsyncSession) -> dict[Currency, Decimal]:
    """All five balances in the display order, zeros included (TZ 13.7)."""
    rows = await session.execute(
        select(OperationEntry.currency, func.sum(OperationEntry.delta))
        .where(OperationEntry.kind == EntryKind.CASH)
        .group_by(OperationEntry.currency)
    )
    totals = {currency: total for currency, total in rows}
    return {currency: totals.get(currency, ZERO) for currency in CURRENCIES}


async def obligation(
    session: AsyncSession, client_id: int, book: Book, currency: Currency
) -> Decimal:
    """Above zero the client owes us, below zero we owe the client (TZ 6.1)."""
    total = await session.scalar(
        select(func.sum(OperationEntry.delta)).where(
            OperationEntry.kind == EntryKind.OBLIGATION,
            OperationEntry.client_id == client_id,
            OperationEntry.book == book,
            OperationEntry.currency == currency,
        )
    )
    return total if total is not None else ZERO


async def client_obligations(
    session: AsyncSession, client_id: int
) -> dict[tuple[Book, Currency], Decimal]:
    """Non-zero obligations of a client, exchange book first, currencies in display order."""
    rows = await session.execute(
        select(OperationEntry.book, OperationEntry.currency, func.sum(OperationEntry.delta))
        .where(OperationEntry.kind == EntryKind.OBLIGATION, OperationEntry.client_id == client_id)
        .group_by(OperationEntry.book, OperationEntry.currency)
    )
    totals = {(book, currency): total for book, currency, total in rows if total != 0}
    order = [(book, currency) for book in Book for currency in CURRENCIES]
    return {key: totals[key] for key in order if key in totals}


@dataclass(frozen=True)
class ObligationLine:
    client_id: int
    client: str
    currency: Currency
    amount: Decimal  # signed: above zero the client owes us


async def obligation_lines(session: AsyncSession, book: Book) -> list[ObligationLine]:
    """Every non-zero obligation of a book: one line per client and currency."""
    rows = await session.execute(
        select(Client.id, Client.name, OperationEntry.currency, func.sum(OperationEntry.delta))
        .join(Client, Client.id == OperationEntry.client_id)
        .where(OperationEntry.kind == EntryKind.OBLIGATION, OperationEntry.book == book)
        .group_by(Client.id, Client.name, OperationEntry.currency)
    )
    return [
        ObligationLine(client_id, name, currency, total)
        for client_id, name, currency, total in rows
        if total != 0
    ]


async def operation_by_request(session: AsyncSession, request_id: uuid.UUID) -> Operation | None:
    return await session.scalar(select(Operation).where(Operation.request_id == request_id))


async def reversal_of(session: AsyncSession, operation_id: int) -> Operation | None:
    return await session.scalar(select(Operation).where(Operation.reversal_of_id == operation_id))


async def get_operation(session: AsyncSession, operation_id: int) -> Operation:
    """A record with its client, author and entries loaded."""
    operation = await session.scalar(
        select(Operation)
        .where(Operation.id == operation_id)
        .options(
            joinedload(Operation.client),
            joinedload(Operation.author),
            selectinload(Operation.entries),
        )
        .execution_options(populate_existing=True)
    )
    if operation is None:
        raise OperationNotFound(operation_id)
    return operation


async def require_client(tx: AsyncSession, client_id: int | None) -> None:
    if client_id is not None and await tx.get(Client, client_id) is None:
        raise ClientNotFound(client_id)


async def _open_day_id(tx: AsyncSession) -> int:
    """TZ 7.3: the shared lock keeps the day open until this record is written.

    If the day was closed while we waited for the lock, the row no longer matches and the
    next day is not in this statement's snapshot yet; a second statement sees it.
    """
    for _ in range(2):
        day_id = await tx.scalar(
            select(BusinessDay.id)
            .where(BusinessDay.status == DayStatus.OPEN)
            .with_for_update(read=True)
        )
        if day_id is not None:
            return day_id
    raise RuntimeError("no open business day: the bot opens one on start")


async def post(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    draft: Draft,
    *,
    reversal_of_id: int | None = None,
    reversal_reason: str | None = None,
    lock_also: Iterable[Currency] = (),
    check: Check | None = None,
) -> tuple[Operation, bool]:
    """Save a record. Returns (record, created); a repeated request_id returns the first one."""
    ensure_active(actor)
    changes = cash_changes(draft.entries)
    lowered = sorted((c for c, delta in changes.items() if delta < 0), key=CURRENCIES.index)
    try:
        async with isolated(session) as tx:
            day_id = await _open_day_id(tx)
            await lock_balances(tx, [*lowered, *lock_also])
            existing = await operation_by_request(tx, request_id)
            if existing is not None:
                return existing, False
            await require_client(tx, draft.client_id)
            if check is not None:
                await check(tx)
            for currency in lowered:
                available = await balance(tx, currency)
                if available + changes[currency] < 0:
                    raise InsufficientBalance(currency, available, -changes[currency])
            operation = Operation(
                request_id=request_id,
                day_id=day_id,
                type=draft.type,
                client_id=draft.client_id,
                currency=draft.currency,
                amount=draft.amount,
                give_currency=draft.give_currency,
                give_amount=draft.give_amount,
                get_currency=draft.get_currency,
                get_amount=draft.get_amount,
                rate=draft.rate,
                rate_base=draft.rate_base,
                rate_quote=draft.rate_quote,
                received_now=draft.received_now,
                paid_now=draft.paid_now,
                comment=draft.comment,
                reason=draft.reason,
                author_id=actor.id,
                reversal_of_id=reversal_of_id,
                reversal_reason=reversal_reason,
            )
            tx.add(operation)
            await tx.flush()
            tx.add_all(
                OperationEntry(
                    operation_id=operation.id,
                    kind=entry.kind,
                    currency=entry.currency,
                    book=entry.book,
                    client_id=entry.client_id,
                    delta=entry.delta,
                )
                for entry in draft.entries
            )
        return operation, True
    except IntegrityError:
        # A parallel save with the same request_id won the unique index.
        existing = await operation_by_request(session, request_id)
        if existing is not None:
            return existing, False
        raise
