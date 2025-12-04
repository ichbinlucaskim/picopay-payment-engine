from sqlalchemy import ForeignKey, Enum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, Optional
import enum
import uuid
from app.database import Base


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    balance: Mapped[float] = mapped_column(default=0.0)

    transactions: Mapped[List["Transaction"]] = relationship(back_populates="user")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column()
    currency: Mapped[str] = mapped_column()
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus), default=TransactionStatus.PENDING
    )
    idempotency_key: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True, nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="transactions")

