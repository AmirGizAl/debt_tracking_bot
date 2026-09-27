"""initial schema: users, clients, operations, cash_adjustments

Revision ID: 0001
Revises:
Create Date: 2026-09-27

Autogenerate does not see triggers, and does not compare CHECK constraints or the predicates
of partial indexes, so everything below is written by hand. Keep app/db/models.py in sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

currency = postgresql.ENUM("KGS", "USD", "EUR", "RUB", "KZT", name="currency", create_type=False)
operation_type = postgresql.ENUM(
    "lend", "repay_in", "borrow", "repay_out", name="operation_type", create_type=False
)
user_role = postgresql.ENUM("owner", "helper", name="user_role", create_type=False)
user_status = postgresql.ENUM("pending", "active", "deleted", name="user_status", create_type=False)

JOURNAL_TABLES = ("operations", "cash_adjustments")


def upgrade() -> None:
    bind = op.get_bind()
    for enum in (currency, operation_type, user_role, user_status):
        enum.create(bind)

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=32), nullable=True),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("role", user_role, nullable=False),
        sa.Column("status", user_status, nullable=False),
        sa.Column("added_by_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["added_by_id"], ["users.id"], name=op.f("fk_users_added_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "uq_users_telegram_id",
        "users",
        ["telegram_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted' AND telegram_id IS NOT NULL"),
    )
    op.create_index(
        "uq_users_username",
        "users",
        ["username"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_clients_created_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_index("uq_clients_name_lower", "clients", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "operations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("type", operation_type, nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("debt_currency", currency, nullable=False),
        sa.Column("debt_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cash_currency", currency, nullable=False),
        sa.Column("cash_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("rate_base", currency, nullable=True),
        sa.Column("rate_quote", currency, nullable=True),
        sa.Column("debt_delta", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cash_delta", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("op_date", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reversal_of_id", sa.BigInteger(), nullable=True),
        sa.Column("reversal_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "debt_amount > 0 AND cash_amount > 0",
            name=op.f("ck_operations_amounts_positive"),
        ),
        sa.CheckConstraint(
            "(debt_currency = cash_currency AND debt_amount = cash_amount"
            " AND rate IS NULL AND rate_base IS NULL AND rate_quote IS NULL)"
            " OR (debt_currency <> cash_currency"
            " AND rate IS NOT NULL AND rate_base IS NOT NULL AND rate_quote IS NOT NULL"
            " AND ((rate_base = debt_currency AND rate_quote = cash_currency)"
            " OR (rate_base = cash_currency AND rate_quote = debt_currency)))",
            name=op.f("ck_operations_currency_rate"),
        ),
        sa.CheckConstraint("rate IS NULL OR rate > 0", name=op.f("ck_operations_rate_positive")),
        sa.CheckConstraint(
            "type NOT IN ('lend', 'borrow') OR debt_currency = cash_currency",
            name=op.f("ck_operations_new_debt_single_currency"),
        ),
        sa.CheckConstraint(
            "reversal_of_id IS NULL OR reversal_reason IS NOT NULL",
            name=op.f("ck_operations_reversal_reason_required"),
        ),
        sa.CheckConstraint(
            "debt_delta = CASE WHEN (type IN ('lend', 'repay_out')) = (reversal_of_id IS NULL)"
            " THEN debt_amount ELSE -debt_amount END"
            " AND cash_delta = CASE WHEN (type IN ('lend', 'repay_out')) = (reversal_of_id IS NULL)"
            " THEN -cash_amount ELSE cash_amount END",
            name=op.f("ck_operations_deltas_match_type"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_operations_author_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_operations_client_id_clients"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"],
            ["operations.id"],
            name=op.f("fk_operations_reversal_of_id_operations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operations")),
        sa.UniqueConstraint("request_id", name=op.f("uq_operations_request_id")),
        sa.UniqueConstraint("reversal_of_id", name=op.f("uq_operations_reversal_of_id")),
    )
    op.create_index(op.f("ix_operations_op_date"), "operations", ["op_date"])
    op.create_index(
        "ix_operations_client_id_debt_currency", "operations", ["client_id", "debt_currency"]
    )
    op.create_index("ix_operations_cash_currency", "operations", ["cash_currency"])

    op.create_table(
        "cash_adjustments",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("currency", currency, nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("adj_date", sa.Date(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount <> 0", name=op.f("ck_cash_adjustments_amount_nonzero")),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_cash_adjustments_author_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_adjustments")),
        sa.UniqueConstraint("request_id", name=op.f("uq_cash_adjustments_request_id")),
    )
    op.create_index(op.f("ix_cash_adjustments_currency"), "cash_adjustments", ["currency"])

    op.execute(
        """
        CREATE FUNCTION forbid_journal_changes() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% are immutable', TG_TABLE_NAME;
        END;
        $$
        """
    )
    for table in JOURNAL_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION forbid_journal_changes()"
        )


def downgrade() -> None:
    for table in JOURNAL_TABLES:
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.execute("DROP FUNCTION forbid_journal_changes()")

    op.drop_table("cash_adjustments")
    op.drop_table("operations")
    op.drop_table("clients")
    op.drop_table("users")

    bind = op.get_bind()
    for enum in (user_status, user_role, operation_type, currency):
        enum.drop(bind)
