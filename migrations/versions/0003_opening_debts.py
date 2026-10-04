"""opening debts: debts from before the bot, agreed with the customer on 03.10.2026

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03

Two record types: `opening_debt` (book exchange, any currency) and `opening_loan` (book loan,
KGS). They carry a client, a currency and a signed amount (above zero the client owes us)
and post one obligation entry, no money. PostgreSQL does not let a transaction use an enum
value it has just added, so the constraints below compare the type as text. Keep
app/db/models.py in sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TYPES = ("opening_debt", "opening_loan")
AMOUNT_SIGN = (
    "type::text = 'exchange'"
    " OR (type::text IN ('adjustment', 'opening_debt', 'opening_loan') AND amount <> 0)"
    " OR (type::text NOT IN ('exchange', 'adjustment', 'opening_debt', 'opening_loan')"
    " AND amount > 0)"
)
OPENING_DEBT_FIELDS = (
    "type::text NOT IN ('opening_debt', 'opening_loan')"
    " OR (client_id IS NOT NULL AND (type::text = 'opening_debt' OR currency = 'KGS'))"
)
OLD_AMOUNT_SIGN = (
    "type = 'exchange'"
    " OR (type = 'adjustment' AND amount <> 0)"
    " OR (type <> 'adjustment' AND amount > 0)"
)


def upgrade() -> None:
    for value in NEW_TYPES:
        op.execute(f"ALTER TYPE operation_type ADD VALUE IF NOT EXISTS '{value}'")
    op.drop_constraint(op.f("ck_operations_amount_sign"), "operations", type_="check")
    op.create_check_constraint(op.f("ck_operations_amount_sign"), "operations", AMOUNT_SIGN)
    op.create_check_constraint(
        op.f("ck_operations_opening_debt_fields"), "operations", OPENING_DEBT_FIELDS
    )


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM operations"
                " WHERE type::text IN ('opening_debt', 'opening_loan')"
            )
        )
        .scalar_one()
    )
    if count:
        raise RuntimeError(f"{count} records of opening debts: cannot downgrade below 0003")
    op.drop_constraint(op.f("ck_operations_opening_debt_fields"), "operations", type_="check")
    op.drop_constraint(op.f("ck_operations_amount_sign"), "operations", type_="check")
    op.create_check_constraint(op.f("ck_operations_amount_sign"), "operations", OLD_AMOUNT_SIGN)
    # The enum values stay: PostgreSQL cannot drop them, and 0003 adds them only if missing.
