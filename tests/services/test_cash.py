import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CashAdjustment, User
from app.domain import errors
from app.domain.currency import Currency
from app.services import cash
from tests.services.accounting import TODAY, adjust

D = Decimal


async def test_balances_list_every_currency_in_order(session: AsyncSession, owner: User) -> None:
    await adjust(session, owner, "2000", Currency.EUR)
    await adjust(session, owner, "10000", Currency.USD)
    await adjust(session, owner, "-500", Currency.USD, "Личные расходы")

    result = await cash.cash_balances(session)

    assert list(result) == [Currency.KGS, Currency.USD, Currency.EUR, Currency.RUB, Currency.KZT]
    assert result[Currency.USD] == D("9500")
    assert result[Currency.EUR] == D("2000")
    assert result[Currency.KGS] == 0


async def test_adjustment_fields(session: AsyncSession, owner: User) -> None:
    adjustment = await adjust(session, owner, "300000", Currency.KGS, "  Остаток на начало работы ")

    assert adjustment.amount == D("300000")
    assert adjustment.reason == "Остаток на начало работы"
    assert adjustment.adj_date == TODAY
    assert adjustment.author_id == owner.id


async def test_helper_cannot_adjust_cash(session: AsyncSession, helper: User) -> None:
    with pytest.raises(errors.PermissionDenied):
        await adjust(session, helper, "100")


async def test_adjustment_is_idempotent(session: AsyncSession, owner: User) -> None:
    request_id = uuid.uuid4()

    first = await adjust(session, owner, "100", request_id=request_id)
    second = await adjust(session, owner, "100", request_id=request_id)

    assert first.id == second.id
    assert await session.scalar(select(func.count()).select_from(CashAdjustment)) == 1


@pytest.mark.parametrize(
    ("amount", "reason", "error"),
    [
        ("0", "причина", errors.InvalidNumber),
        ("1.005", "причина", errors.InvalidNumber),
        ("1000000000000", "причина", errors.InvalidNumber),
        ("100", "", errors.EmptyText),
        ("100", "я" * 501, errors.TextTooLong),
    ],
)
async def test_adjustment_validation(
    session: AsyncSession, owner: User, amount: str, reason: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        await adjust(session, owner, amount, reason=reason)
