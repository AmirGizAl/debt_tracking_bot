"""Som loans (TZ 6.3, 13.5): «Выдал в долг», «Мне вернули», «Взял в долг», «Я вернул»."""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Operation, User
from app.domain.entries import OperationType, loan_draft
from app.domain.notes import optional_text
from app.services import ledger


async def create_loan(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    op_type: OperationType,
    client_id: int,
    amount: Decimal,
    comment: str | None = None,
) -> tuple[Operation, bool]:
    draft = loan_draft(op_type, client_id, amount, optional_text(comment))
    return await ledger.post(session, actor, request_id, draft)
