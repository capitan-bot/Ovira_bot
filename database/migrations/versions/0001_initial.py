"""initial schema

Revision ID: 0001
Revises:
"""
from alembic import op

import database.models  # noqa: F401
from database.base import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial baseline created from the models. All later changes: `alembic revision --autogenerate`.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
