from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TZDateTime, str_enum, utcnow
from database.models.enums import TxType

# Amounts are stored as integer Toman everywhere (no floats for money).


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    referrer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    wallet: Mapped["Wallet"] = relationship(back_populates="user", uselist=False)


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_wallet_balance_nonneg"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    total_charged: Mapped[int] = mapped_column(BigInteger, default=0)
    total_spent: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="wallet")


class WalletTransaction(Base):
    """Append-only ledger. Every balance change creates exactly one row."""
    __tablename__ = "wallet_transactions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_wallet_tx_idem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[TxType] = mapped_column(str_enum(TxType, "tx_type"))
    amount: Mapped[int] = mapped_column(BigInteger)          # signed (+credit / -debit)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    ref_type: Mapped[str | None] = mapped_column(String(32))  # invoice / order / manual
    ref_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    admin_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
