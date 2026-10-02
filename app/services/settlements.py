"""Payouts and receipts of exchange obligations (TZ 6.3, 13.4)."""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Operation, User
from app.domain.currency import Currency
from app.domain.entries import OperationType, settlement_draft
from app.domain.notes import optional_text
from app.services import ledger


async def create_settlement(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    op_type: OperationType,
    client_id: int,
    currency: Currency,
    amount: Decimal,
    comment: str | None = None,
) -> tuple[Operation, bool]:
    """«Выдача по обмену» or «Получение по обмену»; only in the obligation's currency."""
    draft = settlement_draft(op_type, client_id, currency, amount, optional_text(comment))
    return await ledger.post(session, actor, request_id, draft)
