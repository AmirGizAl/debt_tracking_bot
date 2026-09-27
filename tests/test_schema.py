"""Database-level guarantees: immutable journal, CHECK constraints, models match migration."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.base import Base
from app.db.models import CashAdjustment, Client, Operation, User
from app.domain.currency import Currency
from app.domain.operations import OperationType


@pytest.fixture
async def client(session: AsyncSession, owner: User) -> Client:
    client = Client(name="Азамат", created_by_id=owner.id)
    session.add(client)
    await session.commit()
    return client


def operation_row(owner: User, client: Client, **overrides: Any) -> Operation:
    fields: dict[str, Any] = {
        "request_id": uuid.uuid4(),
        "type": OperationType.LEND,
        "client_id": client.id,
        "debt_currency": Currency.USD,
        "debt_amount": Decimal("100"),
        "cash_currency": Currency.USD,
        "cash_amount": Decimal("100"),
        "debt_delta": Decimal("100"),
        "cash_delta": Decimal("-100"),
        "op_date": date(2026, 9, 27),
        "author_id": owner.id,
    }
    fields.update(overrides)
    return Operation(**fields)


async def insert(session: AsyncSession, row: object) -> None:
    session.add(row)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


@pytest.mark.parametrize(
    "statement",
    ["UPDATE operations SET comment = 'changed'", "DELETE FROM operations"],
)
async def test_operations_are_immutable(
    session: AsyncSession, owner: User, client: Client, statement: str
) -> None:
    await insert(session, operation_row(owner, client))

    with pytest.raises(DBAPIError, match="operations are immutable"):
        await session.execute(text(statement))
    await session.rollback()


@pytest.mark.parametrize(
    "statement",
    ["UPDATE cash_adjustments SET reason = 'changed'", "DELETE FROM cash_adjustments"],
)
async def test_cash_adjustments_are_immutable(
    session: AsyncSession, owner: User, statement: str
) -> None:
    await insert(
        session,
        CashAdjustment(
            request_id=uuid.uuid4(),
            currency=Currency.USD,
            amount=Decimal("10000"),
            reason="Остаток на начало работы",
            adj_date=date(2026, 9, 27),
            author_id=owner.id,
        ),
    )

    with pytest.raises(DBAPIError, match="cash_adjustments are immutable"):
        await session.execute(text(statement))
    await session.rollback()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param(
            {
                "cash_currency": Currency.KGS,
                "cash_amount": Decimal("8750"),
                "cash_delta": Decimal("-8750"),
                "rate": Decimal("87.5"),
                "rate_base": Currency.USD,
                "rate_quote": Currency.KGS,
            },
            "ck_operations_new_debt_single_currency",
            id="lend-in-two-currencies",
        ),
        pytest.param(
            {
                "type": OperationType.REPAY_IN,
                "cash_currency": Currency.KGS,
                "cash_amount": Decimal("8750"),
                "debt_delta": Decimal("-100"),
                "cash_delta": Decimal("8750"),
            },
            "ck_operations_currency_rate",
            id="no-rate-for-different-currencies",
        ),
        pytest.param(
            {"rate": Decimal("1"), "rate_base": Currency.USD, "rate_quote": Currency.USD},
            "ck_operations_currency_rate",
            id="rate-for-same-currency",
        ),
        pytest.param(
            {
                "debt_amount": Decimal("0"),
                "cash_amount": Decimal("0"),
                "debt_delta": 0,
                "cash_delta": 0,
            },
            "ck_operations_amounts_positive",
            id="zero-amount",
        ),
        pytest.param(
            {"debt_delta": Decimal("-100"), "cash_delta": Decimal("100")},
            "ck_operations_deltas_match_type",
            id="wrong-delta-sign",
        ),
    ],
)
async def test_operation_check_constraints(
    session: AsyncSession,
    owner: User,
    client: Client,
    overrides: dict[str, Any],
    constraint: str,
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        await insert(session, operation_row(owner, client, **overrides))


async def test_reversal_requires_reason(session: AsyncSession, owner: User, client: Client) -> None:
    original = operation_row(owner, client)
    await insert(session, original)
    reversal = operation_row(
        owner,
        client,
        reversal_of_id=original.id,
        debt_delta=Decimal("-100"),
        cash_delta=Decimal("100"),
    )

    with pytest.raises(IntegrityError, match="ck_operations_reversal_reason_required"):
        await insert(session, reversal)


async def test_operation_can_be_reversed_only_once(
    session: AsyncSession, owner: User, client: Client
) -> None:
    original = operation_row(owner, client)
    await insert(session, original)
    reversal_fields = {
        "reversal_of_id": original.id,
        "reversal_reason": "ошибка",
        "debt_delta": Decimal("-100"),
        "cash_delta": Decimal("100"),
    }
    await insert(session, operation_row(owner, client, **reversal_fields))

    with pytest.raises(IntegrityError, match="uq_operations_reversal_of_id"):
        await insert(session, operation_row(owner, client, **reversal_fields))


async def test_client_with_operations_cannot_be_deleted(
    session: AsyncSession, owner: User, client: Client
) -> None:
    await insert(session, operation_row(owner, client))

    with pytest.raises(IntegrityError, match="fk_operations_client_id_clients"):
        await session.execute(text("DELETE FROM clients"))
    await session.rollback()


async def test_client_names_are_unique_ignoring_case(session: AsyncSession, owner: User) -> None:
    await insert(session, Client(name="Иван", created_by_id=owner.id))

    with pytest.raises(IntegrityError, match="uq_clients_name_lower"):
        await insert(session, Client(name="иВАН", created_by_id=owner.id))


def _diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection)
    return compare_metadata(context, Base.metadata)


async def test_models_match_migration(engine: AsyncEngine) -> None:
    # Guards `alembic revision --autogenerate` against spurious diffs.
    async with engine.connect() as connection:
        assert await connection.run_sync(_diff) == []
