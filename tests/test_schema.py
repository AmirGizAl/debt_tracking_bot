"""Database-level guarantees (TZ 12): immutable journal, closed days, CHECKs, models = migration."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.base import Base
from app.db.models import (
    BusinessDay,
    Client,
    DayStatus,
    Operation,
    OperationEntry,
    User,
    UserRole,
    UserStatus,
)
from app.domain.currency import Currency
from app.domain.entries import Book, EntryKind, OperationType
from app.services import days

USD, EUR, RUB, KGS = Currency.USD, Currency.EUR, Currency.RUB, Currency.KGS
D = Decimal


@pytest.fixture
async def day(session: AsyncSession) -> BusinessDay:
    return await days.ensure_open_day(session)


@pytest.fixture
async def client(session: AsyncSession, owner: User) -> Client:
    client = Client(name="Азамат", created_by_id=owner.id)
    session.add(client)
    await session.commit()
    return client


def record(day: BusinessDay, owner: User, **fields: Any) -> Operation:
    """A valid opening balance unless the fields say otherwise."""
    values: dict[str, Any] = {
        "request_id": uuid.uuid4(),
        "day_id": day.id,
        "type": OperationType.OPENING,
        "currency": USD,
        "amount": D("100"),
        "author_id": owner.id,
    }
    values.update(fields)
    return Operation(**values)


def exchange(day: BusinessDay, owner: User, **fields: Any) -> Operation:
    """A valid instant exchange without a client: 100 USD for 8 700 KGS at 87."""
    values: dict[str, Any] = {
        "type": OperationType.EXCHANGE,
        "currency": None,
        "amount": None,
        "give_currency": USD,
        "give_amount": D("100"),
        "get_currency": KGS,
        "get_amount": D("8700"),
        "rate": D("87"),
        "rate_base": USD,
        "rate_quote": KGS,
        "received_now": True,
        "paid_now": True,
    }
    values.update(fields)
    return record(day, owner, **values)


def entry(operation: Operation, **fields: Any) -> OperationEntry:
    values: dict[str, Any] = {
        "operation_id": operation.id,
        "kind": EntryKind.CASH,
        "currency": USD,
        "delta": D("100"),
    }
    values.update(fields)
    return OperationEntry(**values)


async def insert(session: AsyncSession, *rows: object) -> None:
    session.add_all(rows)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def close(session: AsyncSession, day: BusinessDay, owner: User) -> None:
    await session.execute(
        text(
            "UPDATE business_days SET status = 'closed', closed_at = now(), closed_by_id = :owner,"
            " rates = '{}', report = '{}', surplus = 0 WHERE id = :day"
        ),
        {"owner": owner.id, "day": day.id},
    )
    await session.commit()


# --- immutability (TZ 12.4, 12.5) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE operations SET comment = 'changed'", "operations are immutable"),
        ("DELETE FROM operations", "operations are immutable"),
        ("UPDATE operation_entries SET delta = 1", "operation_entries are immutable"),
        ("DELETE FROM operation_entries", "operation_entries are immutable"),
    ],
)
async def test_journal_is_immutable(
    session: AsyncSession, day: BusinessDay, owner: User, statement: str, message: str
) -> None:
    operation = record(day, owner)
    await insert(session, operation)
    await insert(session, entry(operation))

    with pytest.raises(DBAPIError, match=message):
        await session.execute(text(statement))
    await session.rollback()


# --- business days (TZ 7, 12.3) ----------------------------------------------------------------


async def test_only_one_day_is_open(session: AsyncSession, day: BusinessDay) -> None:
    with pytest.raises(IntegrityError, match="uq_business_days_open"):
        await insert(session, BusinessDay(status=DayStatus.OPEN))


async def test_closing_keeps_rates_report_and_surplus(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    await close(session, day, owner)

    stored = await session.scalar(
        text("SELECT status::text FROM business_days WHERE id = :id"), {"id": day.id}
    )
    assert stored == "closed"
    with pytest.raises(IntegrityError, match="ck_business_days_closing_fields"):
        await insert(session, BusinessDay(status=DayStatus.CLOSED))


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE business_days SET surplus = 1", "is closed and cannot be changed"),
        ("UPDATE business_days SET status = 'open'", "is closed and cannot be changed"),
        ("DELETE FROM business_days", "business days cannot be deleted"),
    ],
)
async def test_closed_day_never_changes(
    session: AsyncSession, day: BusinessDay, owner: User, statement: str, message: str
) -> None:
    await close(session, day, owner)

    with pytest.raises(DBAPIError, match=message):
        await session.execute(text(statement))
    await session.rollback()


async def test_open_day_cannot_be_deleted(session: AsyncSession, day: BusinessDay) -> None:
    with pytest.raises(DBAPIError, match="business days cannot be deleted"):
        await session.execute(text("DELETE FROM business_days"))
    await session.rollback()


async def test_no_record_lands_in_a_closed_day(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    await close(session, day, owner)

    with pytest.raises(DBAPIError, match=f"business day {day.id} is closed"):
        await insert(session, record(day, owner))


# --- operations: CHECK constraints (TZ 12.4) -----------------------------------------------------


async def test_valid_records(
    session: AsyncSession, day: BusinessDay, owner: User, client: Client
) -> None:
    await insert(
        session,
        record(day, owner),
        record(day, owner, type=OperationType.ADJUSTMENT, amount=D("-50"), reason="недостача"),
        record(day, owner, type=OperationType.LOAN_GIVE, currency=KGS, client_id=client.id),
        record(day, owner, type=OperationType.EXCHANGE_PAYOUT, client_id=client.id),
        exchange(day, owner),
        # Both sides later, with a client.
        exchange(day, owner, client_id=client.id, received_now=False, paid_now=False),
        # A transfer in one currency: different amounts, no rate (TZ 6.4).
        exchange(
            day,
            owner,
            client_id=client.id,
            give_currency=RUB,
            give_amount=D("100000"),
            get_currency=RUB,
            get_amount=D("99000"),
            rate=None,
            rate_base=None,
            rate_quote=None,
            paid_now=False,
        ),
    )


def _loan(**fields: Any) -> dict[str, Any]:
    return {"type": OperationType.LOAN_GIVE, "currency": KGS, **fields}


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        pytest.param({"amount": None}, "fields_by_type", id="no-amount"),
        pytest.param({"give_currency": USD}, "fields_by_type", id="exchange-field-on-opening"),
        pytest.param({"amount": D("-100")}, "amount_sign", id="negative-opening"),
        pytest.param(
            {"type": OperationType.ADJUSTMENT, "amount": D("0"), "reason": "ноль"},
            "amount_sign",
            id="zero-adjustment",
        ),
        pytest.param(
            {"type": OperationType.ADJUSTMENT}, "adjustment_reason", id="adjustment-no-reason"
        ),
        pytest.param({"reason": "лишнее"}, "adjustment_reason", id="reason-on-opening"),
        pytest.param({"comment": "x", "reversal_reason": "x"}, "reversal_reason", id="no-original"),
        pytest.param(_loan(currency=USD), "loan_fields", id="loan-in-usd"),
        pytest.param(_loan(), "loan_fields", id="loan-without-client"),
        pytest.param(
            {"type": OperationType.EXCHANGE_RECEIPT}, "settlement_client", id="receipt-no-client"
        ),
    ],
)
async def test_record_check_constraints(
    session: AsyncSession, day: BusinessDay, owner: User, fields: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=f"ck_operations_{constraint}"):
        await insert(session, record(day, owner, **fields))


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        pytest.param(
            {"type": OperationType.OPENING_DEBT}, "opening_debt_fields", id="debt-without-client"
        ),
        pytest.param(
            {"type": OperationType.OPENING_LOAN, "currency": KGS},
            "opening_debt_fields",
            id="loan-debt-without-client",
        ),
        pytest.param(
            {"type": OperationType.OPENING_DEBT, "amount": D("0")}, "amount_sign", id="zero-debt"
        ),
    ],
)
async def test_opening_debt_check_constraints(
    session: AsyncSession, day: BusinessDay, owner: User, fields: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=f"ck_operations_{constraint}"):
        await insert(session, record(day, owner, **fields))


async def test_opening_debts_need_a_client_and_som_loans_need_kgs(
    session: AsyncSession, day: BusinessDay, owner: User, client: Client
) -> None:
    we_owe = record(
        day, owner, type=OperationType.OPENING_DEBT, client_id=client.id, amount=D("-1000")
    )
    await insert(session, we_owe)  # a debt carries a sign: we owe the client

    with pytest.raises(IntegrityError, match="ck_operations_opening_debt_fields"):
        await insert(
            session,
            record(day, owner, type=OperationType.OPENING_LOAN, client_id=client.id),  # USD
        )


async def test_opening_and_adjustment_have_no_client(
    session: AsyncSession, day: BusinessDay, owner: User, client: Client
) -> None:
    with pytest.raises(IntegrityError, match="ck_operations_no_client"):
        await insert(session, record(day, owner, client_id=client.id))


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        pytest.param(
            {"currency": USD, "amount": D("1")}, "fields_by_type", id="amount-on-exchange"
        ),
        pytest.param({"paid_now": None}, "fields_by_type", id="no-paid-now"),
        pytest.param({"rate": None}, "exchange_rate", id="different-currencies-no-rate"),
        pytest.param({"rate_base": EUR}, "exchange_rate", id="rate-of-another-pair"),
        pytest.param({"rate": D("0")}, "exchange_rate", id="zero-rate"),
        pytest.param(
            {"get_currency": USD, "get_amount": D("99")},
            "exchange_rate",
            id="rate-for-one-currency",
        ),
        pytest.param({"give_amount": D("0")}, "exchange_amounts_positive", id="zero-amount"),
        pytest.param({"paid_now": False}, "exchange_client", id="deferred-without-client"),
        pytest.param(
            {
                "get_currency": USD,
                "get_amount": D("100"),
                "rate": None,
                "rate_base": None,
                "rate_quote": None,
            },
            "exchange_not_empty",
            id="same-currency-same-amount-now",
        ),
    ],
)
async def test_exchange_check_constraints(
    session: AsyncSession, day: BusinessDay, owner: User, fields: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=f"ck_operations_{constraint}"):
        await insert(session, exchange(day, owner, **fields))


async def test_reversal_needs_a_reason_and_happens_once(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    original = record(day, owner)
    await insert(session, original)
    # Rows are built before the first failure: a rollback expires the loaded objects.
    without_reason = record(day, owner, reversal_of_id=original.id)
    first = record(day, owner, reversal_of_id=original.id, reversal_reason="ошибка")
    second = record(day, owner, reversal_of_id=original.id, reversal_reason="ещё раз")

    with pytest.raises(IntegrityError, match="ck_operations_reversal_reason"):
        await insert(session, without_reason)
    await insert(session, first)
    with pytest.raises(IntegrityError, match="uq_operations_reversal_of_id"):
        await insert(session, second)


async def test_adjustment_cannot_be_reversed(
    session: AsyncSession, day: BusinessDay, owner: User
) -> None:
    adjustment = record(day, owner, type=OperationType.ADJUSTMENT, reason="излишек")
    await insert(session, adjustment)

    with pytest.raises(IntegrityError, match="ck_operations_adjustment_irreversible"):
        await insert(
            session,
            record(
                day,
                owner,
                type=OperationType.ADJUSTMENT,
                reason="излишек",
                reversal_of_id=adjustment.id,
                reversal_reason="ошибка",
            ),
        )


# --- entries (TZ 12.5) ---------------------------------------------------------------------------


async def test_valid_entries(
    session: AsyncSession, day: BusinessDay, owner: User, client: Client
) -> None:
    operation = record(day, owner)
    await insert(session, operation)
    await insert(
        session,
        entry(operation),
        entry(
            operation,
            kind=EntryKind.OBLIGATION,
            book=Book.EXCHANGE,
            client_id=client.id,
            delta=D("-100"),
        ),
        entry(
            operation,
            kind=EntryKind.OBLIGATION,
            book=Book.LOAN,
            currency=KGS,
            client_id=client.id,
            delta=D("5000"),
        ),
    )


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        pytest.param({"delta": D("0")}, "delta_nonzero", id="zero-delta"),
        pytest.param({"book": Book.EXCHANGE}, "fields_by_kind", id="cash-with-book"),
        pytest.param({"kind": EntryKind.OBLIGATION}, "fields_by_kind", id="obligation-no-book"),
        pytest.param(
            {"kind": EntryKind.OBLIGATION, "book": Book.LOAN, "currency": USD},
            "loan_kgs",
            id="loan-in-usd",
        ),
    ],
)
async def test_entry_check_constraints(
    session: AsyncSession,
    day: BusinessDay,
    owner: User,
    client: Client,
    fields: dict[str, Any],
    constraint: str,
) -> None:
    operation = record(day, owner)
    await insert(session, operation)
    if fields.get("kind") == EntryKind.OBLIGATION and "book" in fields:
        fields = {**fields, "client_id": client.id}

    with pytest.raises(IntegrityError, match=f"ck_operation_entries_{constraint}"):
        await insert(session, entry(operation, **fields))


# --- clients and users ---------------------------------------------------------------------------


async def test_client_with_records_cannot_be_deleted(
    session: AsyncSession, day: BusinessDay, owner: User, client: Client
) -> None:
    await insert(
        session, record(day, owner, type=OperationType.LOAN_GIVE, currency=KGS, client_id=client.id)
    )

    with pytest.raises(IntegrityError, match="fk_operations_client_id_clients"):
        await session.execute(text("DELETE FROM clients"))
    await session.rollback()


async def test_client_names_are_unique_ignoring_case(session: AsyncSession, owner: User) -> None:
    await insert(session, Client(name="Иван", created_by_id=owner.id))

    with pytest.raises(IntegrityError, match="uq_clients_name_lower"):
        await insert(session, Client(name="иВАН", created_by_id=owner.id))


async def test_usernames_are_unique_among_live_users(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    await insert(
        session,
        # Owners added by id have no username: any number of them is fine (TZ 12.1).
        User(telegram_id=1, role=UserRole.OWNER, status=UserStatus.ACTIVE),
        User(telegram_id=2, role=UserRole.OWNER, status=UserStatus.ACTIVE),
        User(username="aigul_k", role=UserRole.HELPER, status=UserStatus.DELETED, deleted_at=now),
        User(username="aigul_k", role=UserRole.HELPER, status=UserStatus.PENDING),
    )

    with pytest.raises(IntegrityError, match="uq_users_username"):
        await insert(
            session, User(username="aigul_k", role=UserRole.HELPER, status=UserStatus.PENDING)
        )


def _diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection)
    return compare_metadata(context, Base.metadata)


async def test_models_match_migration(engine: AsyncEngine) -> None:
    # Guards `alembic revision --autogenerate` against spurious diffs.
    async with engine.connect() as connection:
        assert await connection.run_sync(_diff) == []
