from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TZDateTime, str_enum, utcnow
from database.models.enums import ServiceStatus


class Service(Base):
    """A customer subscription living on a real panel. Usage fields are a cache; the panel is the source of truth."""
    __tablename__ = "services"
    __table_args__ = (Index("ix_services_panel_username", "panel_id", "username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), unique=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("service_profiles.id"))
    username: Mapped[str] = mapped_column(String(32))
    remote_id: Mapped[str | None] = mapped_column(String(128))     # id/uuid on the panel
    protocol: Mapped[str] = mapped_column(String(32))
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)

    total_bytes: Mapped[int] = mapped_column(BigInteger)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    purchased_days: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    status: Mapped[ServiceStatus] = mapped_column(str_enum(ServiceStatus, "service_status"), default=ServiceStatus.ACTIVE)

    subscription_link: Mapped[str | None] = mapped_column(Text)
    # Original panel file, byte-for-byte, Fernet-encrypted. Filename kept exactly as the panel gave it.
    config_filename: Mapped[str | None] = mapped_column(String(255))
    config_blob_enc: Mapped[bytes | None] = mapped_column(LargeBinary)

    last_synced_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    notified_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_depleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class FreeTest(Base):
    __tablename__ = "free_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
