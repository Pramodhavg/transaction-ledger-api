import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money

UQ_TRANSFER_REFERENCE = "uq_transfers_from_account_id_reference_id"


class Transfer(Base):
    """A money movement between two accounts. Its two ledger legs live in `transactions`."""

    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("from_account_id <> to_account_id", name="different_accounts"),
        UniqueConstraint("from_account_id", "reference_id", name=UQ_TRANSFER_REFERENCE),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    to_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    reference_id: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(255))
    # clock_timestamp() is the time of the insert itself (now() would be the start of the
    # DB transaction), so ordering by created_at matches the order rows were written.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
