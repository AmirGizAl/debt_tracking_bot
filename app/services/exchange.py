"""Exchanges (TZ 6.4, 13.3): instant or with a side settled later."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Operation, User
from app.domain.entries import ExchangeTerms, exchange_draft
from app.domain.notes import optional_text
from app.services import ledger


async def create_exchange(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    terms: ExchangeTerms,
    client_id: int | None = None,
    comment: str | None = None,
) -> tuple[Operation, bool]:
    """Raises ClientRequired, NothingToExchange, InsufficientBalance, ClientNotFound."""
    draft = exchange_draft(terms, client_id, optional_text(comment))
    return await ledger.post(session, actor, request_id, draft)
