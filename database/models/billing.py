from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TZDateTime, str_enum, utcnow
from database.models.enums import (
    DiscountType, InvoiceKind, InvoiceStatus, OrderStatus, ReceiptStatus,
)


class Invoice(Base):
    """
    base_amount  = the real price / wallet top-up amount (this is what counts).
    unique_extra = small random amount only used to recognise the payment.
    payable_amount = base_amount + unique_extra (what the customer transfers).
    The partial unique index guarantees no two ACTIVE invoices share a payable amount.
    """
    __tablename__ = "invoices"
    __table_args__ = (
        Index(
            "uq_invoice_active_payable", "payable_amount", unique=True,
            postgresql_where="status IN ('pending','awaiting_review')",
            sqlite_where="status IN ('pending','awaiting_review')",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[InvoiceKind] = mapped_column(str_enum(InvoiceKind, "invoice_kind"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    base_amount: Mapped[int] = mapped_column(BigInteger)
    unique_extra: Mapped[int] = mapped_column(Integer, default=0)
    payable_amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[InvoiceStatus] = mapped_column(str_enum(InvoiceStatus, "invoice_status"), default=InvoiceStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    paid_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class Receipt(Base):
    """One receipt image submission. Approval is a single guarded UPDATE (status='pending' -> final)."""
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    telegram_file_id: Mapped[str] = mapped_column(String(255))
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(128), unique=True)  # same image can't be reused
    status: Mapped[ReceiptStatus] = mapped_column(str_enum(ReceiptStatus, "receipt_status"), default=ReceiptStatus.PENDING)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)   # admin telegram id
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_order_idem"),
        # one live service username per panel (failed/canceled orders free the name)
        Index(
            "uq_order_live_username", "panel_id", "service_username", unique=True,
            postgresql_where="status NOT IN ('failed','canceled','refunded')",
            sqlite_where="status NOT IN ('failed','canceled','refunded')",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("service_profiles.id"))
    service_username: Mapped[str] = mapped_column(String(32))
    gb: Mapped[int] = mapped_column(Integer)
    days: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(BigInteger)               # price before discount
    discount: Mapped[int] = mapped_column(BigInteger, default=0)
    final_price: Mapped[int] = mapped_column(BigInteger)
    discount_code_id: Mapped[int | None] = mapped_column(ForeignKey("discount_codes.id"))
    status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus, "order_status"), default=OrderStatus.AWAITING_PAYMENT)
    error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)


class DiscountCode(Base):
    __tablename__ = "discount_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    type: Mapped[DiscountType] = mapped_column(str_enum(DiscountType, "discount_type"))
    value: Mapped[int] = mapped_column(BigInteger)               # percent (1-100) or Toman
    max_uses: Mapped[int | None] = mapped_column(Integer)        # None = unlimited
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    is_active: Mapped[bool] = mapped_column(default=True)


class DiscountUse(Base):
    __tablename__ = "discount_uses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_id: Mapped[int] = mapped_column(ForeignKey("discount_codes.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    used_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
