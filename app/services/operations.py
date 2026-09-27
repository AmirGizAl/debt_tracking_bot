"""Creating and reversing records (TZ 7, 8).

Every write runs lock (if cash goes out) -> idempotency check -> balance check -> insert ->
commit in one short isolated transaction, so concurrent users cannot overdraw the cash and a
repeated "Сохранить" (same request_id) returns the record saved the first time.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.models import Client, Operation, User
from app.domain.errors import (
    AlreadyReversed,
    CannotReverseReversal,
    ClientNotFound,
    OperationNotFound,
    PermissionDenied,
)
from app.domain.operations import OperationDraft, compute_terms
from app.services import cash
from app.services.clients import normalize_comment
from app.services.transactions import isolated

COMMENT_MAX = 500


def _ensure_active(actor: User) -> None:
    if not actor.is_active:
        raise PermissionDenied("inactive user")


async def operation_by_request(session: AsyncSession, request_id: uuid.UUID) -> Operation | None:
    return await session.scalar(select(Operation).where(Operation.request_id == request_id))


async def reversal_of(session: AsyncSession, operation_id: int) -> Operation | None:
    return await session.scalar(select(Operation).where(Operation.reversal_of_id == operation_id))


async def get_operation(session: AsyncSession, operation_id: int) -> Operation:
    """A record with its client and author loaded."""
    operation = await session.scalar(
        select(Operation)
        .where(Operation.id == operation_id)
        .options(joinedload(Operation.client), joinedload(Operation.author))
        .execution_options(populate_existing=True)
    )
    if operation is None:
        raise OperationNotFound(operation_id)
    return operation


def can_reverse(actor: User, operation: Operation, reversal: Operation | None) -> bool:
    """Only the author, only once, and a reversal itself cannot be reversed (TZ 8.1)."""
    return (
        actor.is_active
        and operation.author_id == actor.id
        and operation.reversal_of_id is None
        and reversal is None
    )


async def create_operation(
    session: AsyncSession, actor: User, draft: OperationDraft
) -> tuple[Operation, bool]:
    """Save a record. Returns (operation, created)."""
    _ensure_active(actor)
    terms = compute_terms(draft)
    comment = normalize_comment(draft.comment, COMMENT_MAX)
    try:
        async with isolated(session) as tx:
            if terms.cash_delta < 0:
                await cash.lock_cash(tx, draft.cash_currency)
            existing = await operation_by_request(tx, draft.request_id)
            if existing is not None:
                return existing, False
            if await tx.get(Client, draft.client_id) is None:
                raise ClientNotFound(draft.client_id)
            if terms.cash_delta < 0:
                await cash.check_available(tx, draft.cash_currency, -terms.cash_delta)
            operation = Operation(
                request_id=draft.request_id,
                type=draft.type,
                client_id=draft.client_id,
                debt_currency=draft.debt_currency,
                debt_amount=terms.debt_amount,
                cash_currency=draft.cash_currency,
                cash_amount=terms.cash_amount,
                rate=terms.rate,
                rate_base=terms.rate_base,
                rate_quote=terms.rate_quote,
                debt_delta=terms.debt_delta,
                cash_delta=terms.cash_delta,
                op_date=draft.op_date,
                comment=comment,
                author_id=actor.id,
            )
            tx.add(operation)
        return operation, True
    except IntegrityError:
        # A parallel save with the same request_id won the unique index.
        existing = await operation_by_request(session, draft.request_id)
        if existing is not None:
            return existing, False
        raise


async def reverse_operation(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    operation_id: int,
    reason: str,
    today: date,
) -> tuple[Operation, bool]:
    """Cancel a record with a mirror record dated today (TZ 8). Returns (reversal, created)."""
    _ensure_active(actor)
    reason = cash.normalize_reason(reason)
    try:
        async with isolated(session) as tx:
            original = await tx.get(Operation, operation_id)
            if original is None:
                raise OperationNotFound(operation_id)
            if original.reversal_of_id is not None:
                raise CannotReverseReversal(operation_id)
            if original.author_id != actor.id:
                raise PermissionDenied("only the author can cancel a record")
            debt_delta, cash_delta = -original.debt_delta, -original.cash_delta
            if cash_delta < 0:
                await cash.lock_cash(tx, original.cash_currency)
            existing = await operation_by_request(tx, request_id)
            if existing is not None:
                return existing, False
            if await reversal_of(tx, original.id) is not None:
                raise AlreadyReversed(operation_id)
            if cash_delta < 0:
                await cash.check_available(tx, original.cash_currency, -cash_delta)
            reversal = Operation(
                request_id=request_id,
                type=original.type,
                client_id=original.client_id,
                debt_currency=original.debt_currency,
                debt_amount=original.debt_amount,
                cash_currency=original.cash_currency,
                cash_amount=original.cash_amount,
                rate=original.rate,
                rate_base=original.rate_base,
                rate_quote=original.rate_quote,
                debt_delta=debt_delta,
                cash_delta=cash_delta,
                op_date=today,
                comment=None,
                author_id=actor.id,
                reversal_of_id=original.id,
                reversal_reason=reason,
            )
            tx.add(reversal)
        return reversal, True
    except IntegrityError as exc:
        existing = await operation_by_request(session, request_id)
        if existing is not None:
            return existing, False
        if await reversal_of(session, operation_id) is not None:
            # The unique index on reversal_of_id caught a concurrent second reversal.
            raise AlreadyReversed(operation_id) from exc
        raise
