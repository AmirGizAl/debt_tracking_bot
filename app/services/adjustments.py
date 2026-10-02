"""Corrections of a balance after counting the money (TZ 10). Owners only, never cancelled."""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Operation, User
from app.domain.currency import Currency
from app.domain.entries import adjustment_draft
from app.domain.notes import required_text
from app.services import ledger
from app.services.users import require_owner


async def create_adjustment(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    currency: Currency,
    amount: Decimal,
    reason: str,
) -> tuple[Operation, bool]:
    """`amount` is signed: above zero adds money, below zero removes it."""
    require_owner(actor)
    draft = adjustment_draft(currency, amount, required_text(reason))
    return await ledger.post(session, actor, request_id, draft)
