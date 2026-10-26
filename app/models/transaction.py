import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money

UQ_TRANSACTION_REFERENCE = "uq_transactions_account_id_reference_id"


class Transaction(Base):
    """An immutable ledger entry. A DB trigger rejects any UPDATE or DELETE."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("type IN ('credit', 'debit')", name="type_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("balance_after >= 0", name="balance_after_non_negative"),
        # A reference_id is unique per account; other accounts may reuse it.
        UniqueConstraint("account_id", "reference_id", name=UQ_TRANSACTION_REFERENCE),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    type: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Money)
    description: Mapped[str | None] = mapped_column(String(255))
    reference_id: Mapped[str] = mapped_column(String(100))
    # Account balance right after this entry: an audit trail that can be replayed.
    balance_after: Mapped[Decimal] = mapped_column(Money)
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transfers.id", ondelete="RESTRICT")
    )
    # See Transfer.created_at for why this is clock_timestamp() and not now().
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


# Serves the history query (filter by account, newest first) without a separate sort step.
Index(
    "ix_transactions_account_created",
    Transaction.account_id,
    Transaction.created_at.desc(),
    Transaction.id.desc(),
)
