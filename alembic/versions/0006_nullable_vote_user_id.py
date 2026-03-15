"""Make votes.user_id nullable for anonymous votes.

Revision ID: 0006_nullable_vote_user_id
Revises: 0005_add_available_metrics
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_nullable_vote_user_id"
down_revision = "0005_add_available_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("votes", "user_id", existing_type=sa.String(50), nullable=True)


def downgrade() -> None:
    op.alter_column("votes", "user_id", existing_type=sa.String(50), nullable=False)
