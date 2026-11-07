"""panel types: pasarguard / sanaei / ovira

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE panels ALTER COLUMN panel_type TYPE VARCHAR(32)")
    op.execute("UPDATE panels SET panel_type = 'ovira' WHERE panel_type = 'panel_one'")


def downgrade() -> None:
    op.execute("UPDATE panels SET panel_type = 'panel_one' WHERE panel_type = 'ovira'")
