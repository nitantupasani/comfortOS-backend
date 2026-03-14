"""Drop daily_vote_limit from buildings table.

The vote-rate limit is a platform-level constant (votes.py), not a
per-building setting, so the column served no purpose.

Revision ID: 0002_drop_building_daily_vote_limit
Revises: 0001_multi_tenant
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_drop_building_daily_vote_limit"
down_revision = "0001_multi_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE buildings DROP COLUMN IF EXISTS daily_vote_limit")


def downgrade() -> None:
    op.add_column(
        "buildings",
        sa.Column(
            "daily_vote_limit",
            sa.Integer,
            server_default="10",
            nullable=False,
        ),
    )
