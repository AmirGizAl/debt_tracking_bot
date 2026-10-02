"""version 2: business days, operations with entries; the accounting of version 1 is dropped

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02

TZ 16.4: the tables `operations` and `cash_adjustments` of version 1 are dropped together with
their rows (agreed with the customer on 02.10.2026), `users` and `clients` stay. Autogenerate
does not see triggers, CHECK constraints or the predicates of partial indexes, so everything
below is written by hand. Keep app/db/models.py in sync.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

currency = postgresql.ENUM("USD", "EUR", "RUB", "KZT", "KGS", name="currency", create_type=False)
operation_type = postgresql.ENUM(
    "exchange",
    "exchange_payout",
    "exchange_receipt",
    "loan_give",
    "loan_repay_in",
    "loan_take",
    "loan_repay_out",
    "adjustment",
    "opening",
    name="operation_type",
    create_type=False,
)
entry_kind = postgresql.ENUM("cash", "obligation", name="entry_kind", create_type=False)
book = postgresql.ENUM("exchange", "loan", name="book", create_type=False)
day_status = postgresql.ENUM("open", "closed", name="day_status", create_type=False)

# Version 1 types, restored by the downgrade.
v1_currency = postgresql.ENUM("KGS", "USD", "EUR", "RUB", "KZT", name="currency", create_type=False)
v1_operation_type = postgresql.ENUM(
    "lend", "repay_in", "borrow", "repay_out", name="operation_type", create_type=False
)

LOAN_TYPES = "('loan_give', 'loan_repay_in', 'loan_take', 'loan_repay_out')"


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("operations", "cash_adjustments"):
        rows = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if rows:
            logger.warning("Dropping %s rows of %s (version 1)", rows, table)
    # Their triggers go with the tables; forbid_journal_changes() is reused below.
    op.drop_table("cash_adjustments")
    op.drop_table("operations")
    for enum in (v1_operation_type, v1_currency):
        enum.drop(bind)
    for enum in (currency, operation_type, entry_kind, book, day_status):
        enum.create(bind)

    op.drop_index("uq_users_username", table_name="users")
    op.create_index(
        "uq_users_username",
        "users",
        ["username"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted' AND username IS NOT NULL"),
    )

    op.create_table(
        "business_days",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("status", day_status, nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.BigInteger(), nullable=True),
        sa.Column("rates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("surplus", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.CheckConstraint(
            "(status = 'open' AND closed_at IS NULL AND closed_by_id IS NULL AND rates IS NULL"
            " AND report IS NULL AND surplus IS NULL)"
            " OR (status = 'closed' AND closed_at IS NOT NULL AND closed_by_id IS NOT NULL"
            " AND rates IS NOT NULL AND report IS NOT NULL AND surplus IS NOT NULL)",
            name=op.f("ck_business_days_closing_fields"),
        ),
        sa.ForeignKeyConstraint(
            ["closed_by_id"], ["users.id"], name=op.f("fk_business_days_closed_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business_days")),
    )
    op.create_index(
        "uq_business_days_open",
        "business_days",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "operations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("day_id", sa.BigInteger(), nullable=False),
        sa.Column("type", operation_type, nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("currency", currency, nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("give_currency", currency, nullable=True),
        sa.Column("give_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("get_currency", currency, nullable=True),
        sa.Column("get_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("rate", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("rate_base", currency, nullable=True),
        sa.Column("rate_quote", currency, nullable=True),
        sa.Column("received_now", sa.Boolean(), nullable=True),
        sa.Column("paid_now", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        _created_at(),
        sa.Column("reversal_of_id", sa.BigInteger(), nullable=True),
        sa.Column("reversal_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
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
            name=op.f("ck_operations_fields_by_type"),
        ),
        sa.CheckConstraint(
            "type <> 'exchange'"
            " OR (give_currency <> get_currency"
            " AND rate IS NOT NULL AND rate_base IS NOT NULL AND rate_quote IS NOT NULL"
            " AND rate > 0"
            " AND ((rate_base = give_currency AND rate_quote = get_currency)"
            " OR (rate_base = get_currency AND rate_quote = give_currency)))"
            " OR (give_currency = get_currency"
            " AND rate IS NULL AND rate_base IS NULL AND rate_quote IS NULL)",
            name=op.f("ck_operations_exchange_rate"),
        ),
        sa.CheckConstraint(
            "type <> 'exchange' OR (give_amount > 0 AND get_amount > 0)",
            name=op.f("ck_operations_exchange_amounts_positive"),
        ),
        sa.CheckConstraint(
            "type <> 'exchange' OR client_id IS NOT NULL OR (received_now AND paid_now)",
            name=op.f("ck_operations_exchange_client"),
        ),
        sa.CheckConstraint(
            "type <> 'exchange' OR NOT (give_currency = get_currency"
            " AND give_amount = get_amount AND received_now AND paid_now)",
            name=op.f("ck_operations_exchange_not_empty"),
        ),
        sa.CheckConstraint(
            "type = 'exchange'"
            " OR (type = 'adjustment' AND amount <> 0)"
            " OR (type <> 'adjustment' AND amount > 0)",
            name=op.f("ck_operations_amount_sign"),
        ),
        sa.CheckConstraint(
            f"type NOT IN {LOAN_TYPES} OR (currency = 'KGS' AND client_id IS NOT NULL)",
            name=op.f("ck_operations_loan_fields"),
        ),
        sa.CheckConstraint(
            "type NOT IN ('exchange_payout', 'exchange_receipt') OR client_id IS NOT NULL",
            name=op.f("ck_operations_settlement_client"),
        ),
        sa.CheckConstraint(
            "type NOT IN ('adjustment', 'opening') OR client_id IS NULL",
            name=op.f("ck_operations_no_client"),
        ),
        sa.CheckConstraint(
            "(type = 'adjustment') = (reason IS NOT NULL)",
            name=op.f("ck_operations_adjustment_reason"),
        ),
        sa.CheckConstraint(
            "type <> 'adjustment' OR reversal_of_id IS NULL",
            name=op.f("ck_operations_adjustment_irreversible"),
        ),
        sa.CheckConstraint(
            "(reversal_of_id IS NULL) = (reversal_reason IS NULL)",
            name=op.f("ck_operations_reversal_reason"),
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
            ["day_id"], ["business_days.id"], name=op.f("fk_operations_day_id_business_days")
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
    op.create_index(op.f("ix_operations_day_id"), "operations", ["day_id"])
    op.create_index(op.f("ix_operations_client_id"), "operations", ["client_id"])
    op.create_index(op.f("ix_operations_created_at"), "operations", ["created_at"])

    op.create_table(
        "operation_entries",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", entry_kind, nullable=False),
        sa.Column("currency", currency, nullable=False),
        sa.Column("book", book, nullable=True),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("delta", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.CheckConstraint("delta <> 0", name=op.f("ck_operation_entries_delta_nonzero")),
        sa.CheckConstraint(
            "(kind = 'cash' AND book IS NULL AND client_id IS NULL)"
            " OR (kind = 'obligation' AND book IS NOT NULL AND client_id IS NOT NULL)",
            name=op.f("ck_operation_entries_fields_by_kind"),
        ),
        sa.CheckConstraint(
            "book IS NULL OR book <> 'loan' OR currency = 'KGS'",
            name=op.f("ck_operation_entries_loan_kgs"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_operation_entries_client_id_clients"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("fk_operation_entries_operation_id_operations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operation_entries")),
    )
    op.create_index(
        op.f("ix_operation_entries_operation_id"), "operation_entries", ["operation_id"]
    )
    op.create_index("ix_operation_entries_kind_currency", "operation_entries", ["kind", "currency"])
    op.create_index(
        "ix_operation_entries_client_id_book_currency",
        "operation_entries",
        ["client_id", "book", "currency"],
    )

    # TZ 12.3: a closed day never changes, no day is ever deleted.
    op.execute(
        """
        CREATE FUNCTION protect_business_days() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'business days cannot be deleted';
            END IF;
            IF OLD.status = 'closed' THEN
                RAISE EXCEPTION 'business day % is closed and cannot be changed', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER business_days_protected BEFORE UPDATE OR DELETE ON business_days"
        " FOR EACH ROW EXECUTE FUNCTION protect_business_days()"
    )
    # TZ 12.4: a record never lands in a closed day.
    op.execute(
        """
        CREATE FUNCTION forbid_closed_day_records() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (SELECT status FROM business_days WHERE id = NEW.day_id) = 'closed' THEN
                RAISE EXCEPTION 'business day % is closed', NEW.day_id;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER operations_open_day BEFORE INSERT ON operations"
        " FOR EACH ROW EXECUTE FUNCTION forbid_closed_day_records()"
    )
    for table in ("operations", "operation_entries"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION forbid_journal_changes()"
        )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("operation_entries")
    op.drop_table("operations")
    op.drop_table("business_days")
    op.execute("DROP FUNCTION forbid_closed_day_records()")
    op.execute("DROP FUNCTION protect_business_days()")
    for enum in (day_status, book, entry_kind, operation_type, currency):
        enum.drop(bind)
    for enum in (v1_currency, v1_operation_type):
        enum.create(bind)

    op.drop_index("uq_users_username", table_name="users")
    op.create_index(
        "uq_users_username",
        "users",
        ["username"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )

    # The empty tables of version 1, as created by revision 0001.
    op.create_table(
        "operations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("type", v1_operation_type, nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("debt_currency", v1_currency, nullable=False),
        sa.Column("debt_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cash_currency", v1_currency, nullable=False),
        sa.Column("cash_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("rate_base", v1_currency, nullable=True),
        sa.Column("rate_quote", v1_currency, nullable=True),
        sa.Column("debt_delta", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cash_delta", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("op_date", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        _created_at(),
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
        sa.Column("currency", v1_currency, nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("adj_date", sa.Date(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        _created_at(),
        sa.CheckConstraint("amount <> 0", name=op.f("ck_cash_adjustments_amount_nonzero")),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_cash_adjustments_author_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_adjustments")),
        sa.UniqueConstraint("request_id", name=op.f("uq_cash_adjustments_request_id")),
    )
    op.create_index(op.f("ix_cash_adjustments_currency"), "cash_adjustments", ["currency"])
    for table in ("operations", "cash_adjustments"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION forbid_journal_changes()"
        )
