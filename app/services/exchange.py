"""Exchanges (TZ 6.4, 13.3): instant or with a side settled later."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BusinessDay, DayStatus, Operation, User
from app.domain.currency import Currency
from app.domain.entries import ExchangeTerms, OperationType, exchange_draft
from app.domain.notes import optional_text
from app.domain.rates import rate_pair
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


async def last_rate_today(
    session: AsyncSession, first: Currency, second: Currency
) -> Decimal | None:
    """The rate of the latest exchange of this pair in the open day (TZ 13.3 step 4)."""
    base, quote = rate_pair(first, second)
    return await session.scalar(
        select(Operation.rate)
        .join(BusinessDay, BusinessDay.id == Operation.day_id)
        .where(
            BusinessDay.status == DayStatus.OPEN,
            Operation.type == OperationType.EXCHANGE,
            Operation.reversal_of_id.is_(None),
            Operation.rate_base == base,
            Operation.rate_quote == quote,
        )
        .order_by(Operation.id.desc())
        .limit(1)
    )
