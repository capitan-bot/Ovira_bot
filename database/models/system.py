from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TZDateTime, str_enum, utcnow
from database.models.enums import TicketStatus, TicketTopic


class Setting(Base):
    """Key/value store for everything the admin edits from the dashboard (texts, card info, test limits...)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))
    topic: Mapped[TicketTopic] = mapped_column(str_enum(TicketTopic, "ticket_topic"))
    status: Mapped[TicketStatus] = mapped_column(str_enum(TicketStatus, "ticket_status"), default=TicketStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    from_admin: Mapped[bool] = mapped_column(default=False)
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class AuditLog(Base):
    """Every sensitive action (money, panel calls, admin edits) is recorded here. Never store secrets in `details`."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))        # "admin:7010190804" / "user:123" / "system"
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
