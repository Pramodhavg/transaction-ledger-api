import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        # Last line of defence: even buggy code or manual SQL cannot overdraw an account.
        CheckConstraint("balance >= 0", name="balance_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100))
    balance: Mapped[Decimal] = mapped_column(
        Money, default=Decimal("0.00"), server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
