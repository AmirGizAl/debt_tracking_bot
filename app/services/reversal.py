"""Cancellation of records (TZ 11): a mirror record in the open day, never an edit."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Operation, User
from app.domain.entries import Draft, Entry, OperationType
from app.domain.errors import (
    AlreadyReversed,
    BaselineFrozen,
    CannotReverse,
    CannotReverseReason,
    PermissionDenied,
)
from app.domain.notes import required_text
from app.services import ledger, opening


def can_reverse(
    actor: User, operation: Operation, reversal: Operation | None, frozen: bool
) -> bool:
    """Whether the card shows «Отменить запись» (TZ 11.1)."""
    return (
        actor.is_active
        and operation.author_id == actor.id
        and operation.reversal_of_id is None
        and reversal is None
        and operation.type != OperationType.ADJUSTMENT
        and not (operation.type == OperationType.OPENING and frozen)
    )


def mirror(original: Operation) -> Draft:
    """The same type and fields; every entry with the opposite sign."""
    return Draft(
        type=original.type,
        entries=tuple(
            Entry(
                kind=entry.kind,
                currency=entry.currency,
                delta=-entry.delta,
                book=entry.book,
                client_id=entry.client_id,
            )
            for entry in original.entries
        ),
        client_id=original.client_id,
        currency=original.currency,
        amount=original.amount,
        give_currency=original.give_currency,
        give_amount=original.give_amount,
        get_currency=original.get_currency,
        get_amount=original.get_amount,
        rate=original.rate,
        rate_base=original.rate_base,
        rate_quote=original.rate_quote,
        received_now=original.received_now,
        paid_now=original.paid_now,
    )


async def reverse(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    operation_id: int,
    reason: str,
) -> tuple[Operation, bool]:
    """Returns (cancellation, created). Only the author, only once (TZ 11)."""
    reason = required_text(reason)
    original = await ledger.get_operation(session, operation_id)
    if original.reversal_of_id is not None:
        raise CannotReverse(CannotReverseReason.REVERSAL)
    if original.type == OperationType.ADJUSTMENT:
        raise CannotReverse(CannotReverseReason.ADJUSTMENT)
    if original.author_id != actor.id:
        raise PermissionDenied("only the author can cancel a record")

    async def check(tx: AsyncSession) -> None:
        if await ledger.reversal_of(tx, original.id) is not None:
            raise AlreadyReversed(operation_id)
        if original.type == OperationType.OPENING and await opening.baseline_frozen(tx):
            raise BaselineFrozen()

    try:
        return await ledger.post(
            session,
            actor,
            request_id,
            mirror(original),
            reversal_of_id=original.id,
            reversal_reason=reason,
            check=check,
        )
    except IntegrityError as exc:
        if await ledger.reversal_of(session, original.id) is not None:
            # The unique index on reversal_of_id caught a parallel second cancellation.
            raise AlreadyReversed(operation_id) from exc
        raise
