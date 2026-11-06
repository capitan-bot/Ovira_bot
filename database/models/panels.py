from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TZDateTime, str_enum, utcnow
from database.models.enums import ConnStatus, PanelType


class Panel(Base):
    """A connected VPN panel. Credentials are Fernet-encrypted (see config/crypto.py)."""
    __tablename__ = "panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64))          # admin-editable, shown to customers
    panel_type: Mapped[PanelType] = mapped_column(str_enum(PanelType, "panel_type"))
    api_url: Mapped[str] = mapped_column(String(255))
    username_enc: Mapped[str | None] = mapped_column(Text)
    password_enc: Mapped[str | None] = mapped_column(Text)
    token_enc: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON)               # adapter-specific options
    notes: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sales_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    conn_status: Mapped[ConnStatus] = mapped_column(str_enum(ConnStatus, "conn_status"), default=ConnStatus.UNKNOWN)
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # --- independent pricing / limits per panel (nothing hard-coded) ---
    price_per_gb: Mapped[int] = mapped_column(BigInteger, default=5500)
    price_per_day: Mapped[int] = mapped_column(BigInteger, default=150)
    min_gb: Mapped[int] = mapped_column(Integer, default=10)
    max_gb: Mapped[int] = mapped_column(Integer, default=200)
    min_days: Mapped[int] = mapped_column(Integer, default=30)
    max_days: Mapped[int] = mapped_column(Integer, default=90)
    min_charge: Mapped[int] = mapped_column(BigInteger, default=10000)
    max_charge: Mapped[int] = mapped_column(BigInteger, default=5000000)
    unique_extra_min: Mapped[int] = mapped_column(Integer, default=1)
    unique_extra_max: Mapped[int] = mapped_column(Integer, default=99)

    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class ServiceProfile(Base):
    __tablename__ = "service_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    protocol: Mapped[str] = mapped_column(String(32))              # vless / wireguard / openvpn ...
    # Ordered list, highest priority first: [{"id": 3, "remark": "DE-1"}, ...] (fetched from the real panel)
    inbounds: Mapped[list | None] = mapped_column(JSON)
    settings: Mapped[dict | None] = mapped_column(JSON)            # user-creation options passed to the adapter
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sales_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
