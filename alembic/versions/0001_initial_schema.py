"""initial schema: accounts, transfers, transactions and the immutability trigger

Revision ID: 0001
Revises:
Create Date: 2026-10-26

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 2)
LEDGER_TABLES = ("transactions", "transfers")

# Ledger rows are append-only: any UPDATE or DELETE is rejected by the database itself,
# not just by the absence of API routes. Corrections are made with new entries.
CREATE_IMMUTABILITY_FUNCTION = """
CREATE FUNCTION prevent_ledger_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$
"""


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("balance", MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_accounts_name_not_blank")),
        sa.CheckConstraint("balance >= 0", name=op.f("ck_accounts_balance_non_negative")),
    )

    op.create_table(
        "transfers",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("from_account_id", sa.Uuid(), nullable=False),
        sa.Column("to_account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("reference_id", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transfers")),
        sa.ForeignKeyConstraint(
            ["from_account_id"],
            ["accounts.id"],
            name=op.f("fk_transfers_from_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_account_id"],
            ["accounts.id"],
            name=op.f("fk_transfers_to_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_transfers_amount_positive")),
        sa.CheckConstraint(
            "from_account_id <> to_account_id", name=op.f("ck_transfers_different_accounts")
        ),
        sa.UniqueConstraint(
            "from_account_id",
            "reference_id",
            name=op.f("uq_transfers_from_account_id_reference_id"),
        ),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("reference_id", sa.String(100), nullable=False),
        sa.Column("balance_after", MONEY, nullable=False),
        sa.Column("transfer_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_transactions_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["transfers.id"],
            name=op.f("fk_transactions_transfer_id_transfers"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("type IN ('credit', 'debit')", name=op.f("ck_transactions_type_valid")),
        sa.CheckConstraint("amount > 0", name=op.f("ck_transactions_amount_positive")),
        sa.CheckConstraint(
            "balance_after >= 0", name=op.f("ck_transactions_balance_after_non_negative")
        ),
        sa.UniqueConstraint(
            "account_id", "reference_id", name=op.f("uq_transactions_account_id_reference_id")
        ),
    )
    op.create_index(
        "ix_transactions_account_created",
        "transactions",
        ["account_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.execute(CREATE_IMMUTABILITY_FUNCTION)
    for table in LEDGER_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_ledger_mutation()"
        )


def downgrade() -> None:
    for table in LEDGER_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_ledger_mutation()")
    op.drop_index("ix_transactions_account_created", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("transfers")
    op.drop_table("accounts")
