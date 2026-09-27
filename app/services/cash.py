"""Cash per currency: never stored, always summed from the journal (TZ 7.3, 7.4, 12.7)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CashAdjustment, Operation, User
from app.domain.currency import CURRENCIES, Currency
from app.domain.errors import EmptyText, InsufficientCash, InvalidNumber, NumberProblem, TextTooLong
from app.domain.money import MAX_AMOUNT, quantize_money
from app.services.transactions import isolated
from app.services.users import require_owner

ZERO = Decimal("0.00")
REASON_MAX = 500

# pg_advisory_xact_lock(namespace, key): one lock per cash currency.
LOCK_NAMESPACE = 7401
_LOCK_KEYS = {currency: number for number, currency in enumerate(CURRENCIES, start=1)}


def normalize_reason(raw: str | None, limit: int = REASON_MAX) -> str:
    """Mandatory free text of 1..limit characters (reasons of reversals and adjustments)."""
    reason = (raw or "").strip()
    if not reason:
        raise EmptyText
    if len(reason) > limit:
        raise TextTooLong(limit)
    return reason


async def lock_cash(session: AsyncSession, currency: Currency) -> None:
    """Serialize everything that takes money out of this currency's cash.

    Held until the end of the current transaction, so check-then-insert is atomic: two
    users cannot spend the same money at once (TZ 7.4).
    """
    await session.execute(select(func.pg_advisory_xact_lock(LOCK_NAMESPACE, _LOCK_KEYS[currency])))


async def cash_balance(session: AsyncSession, currency: Currency) -> Decimal:
    from_operations = (
        select(func.coalesce(func.sum(Operation.cash_delta), 0))
        .where(Operation.cash_currency == currency)
        .scalar_subquery()
    )
    from_adjustments = (
        select(func.coalesce(func.sum(CashAdjustment.amount), 0))
        .where(CashAdjustment.currency == currency)
        .scalar_subquery()
    )
    total = await session.scalar(select(from_operations + from_adjustments))
    return quantize_money(total if total is not None else ZERO)


async def cash_balances(session: AsyncSession) -> dict[Currency, Decimal]:
    """All five currencies in display order, zeros included."""
    balances = dict.fromkeys(CURRENCIES, ZERO)
    operations = await session.execute(
        select(Operation.cash_currency, func.sum(Operation.cash_delta)).group_by(
            Operation.cash_currency
        )
    )
    adjustments = await session.execute(
        select(CashAdjustment.currency, func.sum(CashAdjustment.amount)).group_by(
            CashAdjustment.currency
        )
    )
    for currency, total in [*operations, *adjustments]:
        balances[currency] += total
    return {currency: quantize_money(value) for currency, value in balances.items()}


async def check_available(session: AsyncSession, currency: Currency, outflow: Decimal) -> Decimal:
    """Raise InsufficientCash if taking `outflow` would make the cash negative right now.

    Returns the current balance. Must run after `lock_cash` when used before a write.
    """
    available = await cash_balance(session, currency)
    if available < outflow:
        raise InsufficientCash(currency, available, outflow)
    return available


async def adjustment_by_request(
    session: AsyncSession, request_id: uuid.UUID
) -> CashAdjustment | None:
    return await session.scalar(
        select(CashAdjustment).where(CashAdjustment.request_id == request_id)
    )


async def create_adjustment(
    session: AsyncSession,
    actor: User,
    request_id: uuid.UUID,
    currency: Currency,
    amount: Decimal,
    reason: str,
    today: date,
) -> tuple[CashAdjustment, bool]:
    """Owner-only manual correction (TZ 12.7). Returns (adjustment, created).

    A repeated call with the same request_id returns the adjustment saved the first time.
    """
    require_owner(actor)
    if amount == 0 or amount != quantize_money(amount):
        raise InvalidNumber(NumberProblem.FORMAT)
    if abs(amount) > MAX_AMOUNT:
        raise InvalidNumber(NumberProblem.TOO_LARGE)
    reason = normalize_reason(reason)
    try:
        async with isolated(session) as tx:
            if amount < 0:
                await lock_cash(tx, currency)
            existing = await adjustment_by_request(tx, request_id)
            if existing is not None:
                return existing, False
            if amount < 0:
                await check_available(tx, currency, -amount)
            adjustment = CashAdjustment(
                request_id=request_id,
                currency=currency,
                amount=amount,
                reason=reason,
                adj_date=today,
                author_id=actor.id,
            )
            tx.add(adjustment)
        return adjustment, True
    except IntegrityError:
        existing = await adjustment_by_request(session, request_id)
        if existing is not None:
            return existing, False
        raise
