"""Direct inserts for test setup (bypassing services where a test needs exact control)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Client, Operation, OperationEntry, User
from app.domain.currency import Currency
from app.domain.entries import Book, EntryKind, OperationType
from app.services import days

# The obligation of the client grows for these loan records and shrinks for the others (TZ 6.3).
LOAN_OBLIGATION_SIGN = {
    OperationType.LOAN_GIVE: 1,
    OperationType.LOAN_REPAY_IN: -1,
    OperationType.LOAN_TAKE: -1,
    OperationType.LOAN_REPAY_OUT: 1,
}


async def make_client(
    session: AsyncSession,
    author: User,
    name: str,
    *,
    comment: str | None = None,
    created_at: datetime | None = None,
) -> Client:
    client = Client(name=name, comment=comment, created_by_id=author.id)
    if created_at is not None:
        client.created_at = created_at
    session.add(client)
    await session.commit()
    return client


async def make_loan(
    session: AsyncSession,
    author: User,
    client: Client,
    amount: str,
    op_type: OperationType = OperationType.LOAN_GIVE,
    *,
    created_at: datetime | None = None,
) -> Operation:
    """A som loan record with its two entries, in the open day."""
    day = await days.ensure_open_day(session)
    value = Decimal(amount)
    sign = LOAN_OBLIGATION_SIGN[op_type]
    operation = Operation(
        request_id=uuid.uuid4(),
        day_id=day.id,
        type=op_type,
        client_id=client.id,
        currency=Currency.KGS,
        amount=value,
        author_id=author.id,
    )
    if created_at is not None:
        operation.created_at = created_at
    session.add(operation)
    await session.flush()
    session.add_all(
        [
            OperationEntry(
                operation_id=operation.id,
                kind=EntryKind.CASH,
                currency=Currency.KGS,
                delta=-sign * value,
            ),
            OperationEntry(
                operation_id=operation.id,
                kind=EntryKind.OBLIGATION,
                currency=Currency.KGS,
                book=Book.LOAN,
                client_id=client.id,
                delta=sign * value,
            ),
        ]
    )
    await session.commit()
    return operation
