import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def str_enum(enum_cls: type[enum.Enum], name: str):
    """Store enums as VARCHAR + CHECK (easy to migrate, no PG ENUM types)."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


TZDateTime = DateTime(timezone=True)
