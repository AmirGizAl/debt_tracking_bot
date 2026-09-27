import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.currency import Currency
from app.domain.operations import OperationType

MONEY = Numeric(18, 2)
RATE = Numeric(18, 6)


class UserRole(StrEnum):
    OWNER = "owner"
    HELPER = "helper"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DELETED = "deleted"


def _pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


CURRENCY_ENUM = _pg_enum(Currency, "currency")
OPERATION_TYPE_ENUM = _pg_enum(OperationType, "operation_type")
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
            postgresql_where=text("status <> 'deleted'"),
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


class Operation(Base):
    """Immutable journal record. Corrections are made by reversal records only."""

    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    type: Mapped[OperationType] = mapped_column(OPERATION_TYPE_ENUM)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    debt_currency: Mapped[Currency] = mapped_column(CURRENCY_ENUM)
    debt_amount: Mapped[Decimal] = mapped_column(MONEY)
    cash_currency: Mapped[Currency] = mapped_column(CURRENCY_ENUM)
    cash_amount: Mapped[Decimal] = mapped_column(MONEY)
    rate: Mapped[Decimal | None] = mapped_column(RATE)
    rate_base: Mapped[Currency | None] = mapped_column(CURRENCY_ENUM)
    rate_quote: Mapped[Currency | None] = mapped_column(CURRENCY_ENUM)
    debt_delta: Mapped[Decimal] = mapped_column(MONEY)
    cash_delta: Mapped[Decimal] = mapped_column(MONEY)
    op_date: Mapped[date] = mapped_column(Date, index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reversal_of_id: Mapped[int | None] = mapped_column(ForeignKey("operations.id"), unique=True)
    reversal_reason: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client] = relationship(lazy="raise")
    author: Mapped[User] = relationship(lazy="raise")

    __table_args__ = (
        CheckConstraint("debt_amount > 0 AND cash_amount > 0", name="amounts_positive"),
        CheckConstraint(
            "(debt_currency = cash_currency AND debt_amount = cash_amount"
            " AND rate IS NULL AND rate_base IS NULL AND rate_quote IS NULL)"
            " OR (debt_currency <> cash_currency"
            " AND rate IS NOT NULL AND rate_base IS NOT NULL AND rate_quote IS NOT NULL"
            " AND ((rate_base = debt_currency AND rate_quote = cash_currency)"
            " OR (rate_base = cash_currency AND rate_quote = debt_currency)))",
            name="currency_rate",
        ),
        CheckConstraint("rate IS NULL OR rate > 0", name="rate_positive"),
        CheckConstraint(
            "type NOT IN ('lend', 'borrow') OR debt_currency = cash_currency",
            name="new_debt_single_currency",
        ),
        CheckConstraint(
            "reversal_of_id IS NULL OR reversal_reason IS NOT NULL",
            name="reversal_reason_required",
        ),
        # TZ 7.1: lend/repay_out raise the client's debt and take cash; repay_in/borrow do the
        # opposite; a reversal flips both signs.
        CheckConstraint(
            "debt_delta = CASE WHEN (type IN ('lend', 'repay_out')) = (reversal_of_id IS NULL)"
            " THEN debt_amount ELSE -debt_amount END"
            " AND cash_delta = CASE WHEN (type IN ('lend', 'repay_out')) = (reversal_of_id IS NULL)"
            " THEN -cash_amount ELSE cash_amount END",
            name="deltas_match_type",
        ),
        Index("ix_operations_client_id_debt_currency", "client_id", "debt_currency"),
        Index("ix_operations_cash_currency", "cash_currency"),
    )


class CashAdjustment(Base):
    """Immutable manual cash correction made by the owner."""

    __tablename__ = "cash_adjustments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    currency: Mapped[Currency] = mapped_column(CURRENCY_ENUM, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    reason: Mapped[str] = mapped_column(Text)
    adj_date: Mapped[date] = mapped_column(Date)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    author: Mapped[User] = relationship(lazy="raise")

    __table_args__ = (CheckConstraint("amount <> 0", name="amount_nonzero"),)
