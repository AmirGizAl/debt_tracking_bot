import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.currency import Currency
from app.domain.entries import Book, EntryKind, OperationType

MONEY = Numeric(18, 2)
RATE = Numeric(18, 6)


class UserRole(StrEnum):
    OWNER = "owner"
    HELPER = "helper"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DELETED = "deleted"


class DayStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


def _pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


CURRENCY_ENUM = _pg_enum(Currency, "currency")
OPERATION_TYPE_ENUM = _pg_enum(OperationType, "operation_type")
ENTRY_KIND_ENUM = _pg_enum(EntryKind, "entry_kind")
BOOK_ENUM = _pg_enum(Book, "book")
DAY_STATUS_ENUM = _pg_enum(DayStatus, "day_status")
USER_ROLE_ENUM = _pg_enum(UserRole, "user_role")
USER_STATUS_ENUM = _pg_enum(UserStatus, "user_status")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(32))
    full_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(USER_ROLE_ENUM)
    status: Mapped[UserStatus] = mapped_column(USER_STATUS_ENUM)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_users_telegram_id",
            "telegram_id",
            unique=True,
            postgresql_where=text("status <> 'deleted' AND telegram_id IS NOT NULL"),
        ),
        Index(
            "uq_users_username",
            "username",
            unique=True,
            postgresql_where=text("status <> 'deleted' AND username IS NOT NULL"),
        ),
    )

    @property
    def is_owner(self) -> bool:
        return self.role == UserRole.OWNER

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    comment: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


Index("uq_clients_name_lower", func.lower(Client.name), unique=True)


class BusinessDay(Base):
    """A working day: from one closing to the next (TZ 7). Exactly one day is open."""

    __tablename__ = "business_days"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[DayStatus] = mapped_column(DAY_STATUS_ENUM)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    rates: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    surplus: Mapped[Decimal | None] = mapped_column(MONEY)

    __table_args__ = (
        Index(
            "uq_business_days_open",
            "status",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        # A closed day keeps its rates, report and surplus; an open day has none of them.
        CheckConstraint(
            "(status = 'open' AND closed_at IS NULL AND closed_by_id IS NULL AND rates IS NULL"
            " AND report IS NULL AND surplus IS NULL)"
            " OR (status = 'closed' AND closed_at IS NOT NULL AND closed_by_id IS NOT NULL"
            " AND rates IS NOT NULL AND report IS NOT NULL AND surplus IS NOT NULL)",
            name="closing_fields",
        ),
    )


LOAN_TYPES_SQL = "('loan_give', 'loan_repay_in', 'loan_take', 'loan_repay_out')"


class Operation(Base):
    """Immutable journal record (TZ 12.4). Corrections are made by reversal records only."""

    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("business_days.id"), index=True)
    type: Mapped[OperationType] = mapped_column(OPERATION_TYPE_ENUM)
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), index=True
    )
    currency: Mapped[Currency | None] = mapped_column(CURRENCY_ENUM)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    give_currency: Mapped[Currency | None] = mapped_column(CURRENCY_ENUM)
    give_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    get_currency: Mapped[Currency | None] = mapped_column(CURRENCY_ENUM)
    get_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    rate: Mapped[Decimal | None] = mapped_column(RATE)
    rate_base: Mapped[Currency | None] = mapped_column(CURRENCY_ENUM)
    rate_quote: Mapped[Currency | None] = mapped_column(CURRENCY_ENUM)
    received_now: Mapped[bool | None] = mapped_column(Boolean)
    paid_now: Mapped[bool | None] = mapped_column(Boolean)
    comment: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    reversal_of_id: Mapped[int | None] = mapped_column(ForeignKey("operations.id"), unique=True)
    reversal_reason: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client | None] = relationship(lazy="raise")
    author: Mapped[User] = relationship(lazy="raise")
    entries: Mapped[list["OperationEntry"]] = relationship(
        back_populates="operation", lazy="raise", order_by="OperationEntry.id"
    )

    __table_args__ = (
        # An exchange has its own fields; every other type has one currency and one amount.
        CheckConstraint(
            "(type = 'exchange'"
            " AND give_currency IS NOT NULL AND give_amount IS NOT NULL"
            " AND get_currency IS NOT NULL AND get_amount IS NOT NULL"
            " AND received_now IS NOT NULL AND paid_now IS NOT NULL"
            " AND currency IS NULL AND amount IS NULL)"
            " OR (type <> 'exchange'"
            " AND currency IS NOT NULL AND amount IS NOT NULL"
            " AND give_currency IS NULL AND give_amount IS NULL"
            " AND get_currency IS NULL AND get_amount IS NULL"
            " AND rate IS NULL AND rate_base IS NULL AND rate_quote IS NULL"
            " AND received_now IS NULL AND paid_now IS NULL)",
            name="fields_by_type",
        ),
        # Different currencies need a rate of their pair; one currency (a transfer) has none.
        # IS NOT NULL is spelled out: a CHECK that evaluates to NULL would let the row in.
        CheckConstraint(
            "type <> 'exchange'"
            " OR (give_currency <> get_currency"
            " AND rate IS NOT NULL AND rate_base IS NOT NULL AND rate_quote IS NOT NULL"
            " AND rate > 0"
            " AND ((rate_base = give_currency AND rate_quote = get_currency)"
            " OR (rate_base = get_currency AND rate_quote = give_currency)))"
            " OR (give_currency = get_currency"
            " AND rate IS NULL AND rate_base IS NULL AND rate_quote IS NULL)",
            name="exchange_rate",
        ),
        CheckConstraint(
            "type <> 'exchange' OR (give_amount > 0 AND get_amount > 0)",
            name="exchange_amounts_positive",
        ),
        CheckConstraint(
            "type <> 'exchange' OR client_id IS NOT NULL OR (received_now AND paid_now)",
            name="exchange_client",
        ),
        # Same currency, same amount, both sides now: there is nothing to record (TZ 6.4).
        CheckConstraint(
            "type <> 'exchange' OR NOT (give_currency = get_currency"
            " AND give_amount = get_amount AND received_now AND paid_now)",
            name="exchange_not_empty",
        ),
        # An adjustment and an opening debt carry a sign; the others are above zero. The type
        # is compared as text: see migration 0003.
        CheckConstraint(
            "type::text = 'exchange'"
            " OR (type::text IN ('adjustment', 'opening_debt', 'opening_loan') AND amount <> 0)"
            " OR (type::text NOT IN ('exchange', 'adjustment', 'opening_debt', 'opening_loan')"
            " AND amount > 0)",
            name="amount_sign",
        ),
        # A debt from before the bot (03.10.2026) has a client; a som loan is in KGS.
        CheckConstraint(
            "type::text NOT IN ('opening_debt', 'opening_loan')"
            " OR (client_id IS NOT NULL AND (type::text = 'opening_debt' OR currency = 'KGS'))",
            name="opening_debt_fields",
        ),
        CheckConstraint(
            f"type NOT IN {LOAN_TYPES_SQL} OR (currency = 'KGS' AND client_id IS NOT NULL)",
            name="loan_fields",
        ),
        CheckConstraint(
            "type NOT IN ('exchange_payout', 'exchange_receipt') OR client_id IS NOT NULL",
            name="settlement_client",
        ),
        CheckConstraint(
            "type NOT IN ('adjustment', 'opening') OR client_id IS NULL",
            name="no_client",
        ),
        CheckConstraint("(type = 'adjustment') = (reason IS NOT NULL)", name="adjustment_reason"),
        CheckConstraint(
            "type <> 'adjustment' OR reversal_of_id IS NULL", name="adjustment_irreversible"
        ),
        CheckConstraint(
            "(reversal_of_id IS NULL) = (reversal_reason IS NULL)", name="reversal_reason"
        ),
    )


class OperationEntry(Base):
    """One posting of a record: a balance change or an obligation change (TZ 12.5)."""

    __tablename__ = "operation_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id"), index=True)
    kind: Mapped[EntryKind] = mapped_column(ENTRY_KIND_ENUM)
    currency: Mapped[Currency] = mapped_column(CURRENCY_ENUM)
    book: Mapped[Book | None] = mapped_column(BOOK_ENUM)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    delta: Mapped[Decimal] = mapped_column(MONEY)

    operation: Mapped[Operation] = relationship(back_populates="entries", lazy="raise")

    __table_args__ = (
        CheckConstraint("delta <> 0", name="delta_nonzero"),
        CheckConstraint(
            "(kind = 'cash' AND book IS NULL AND client_id IS NULL)"
            " OR (kind = 'obligation' AND book IS NOT NULL AND client_id IS NOT NULL)",
            name="fields_by_kind",
        ),
        CheckConstraint("book IS NULL OR book <> 'loan' OR currency = 'KGS'", name="loan_kgs"),
        Index("ix_operation_entries_kind_currency", "kind", "currency"),
        Index("ix_operation_entries_client_id_book_currency", "client_id", "book", "currency"),
    )
