"""Add available_metrics column to building_connectors.

Revision ID: 0005_add_available_metrics
Revises: 0004_building_connectors
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_add_available_metrics"
down_revision = "0004_building_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "building_connectors",
        sa.Column("available_metrics", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("building_connectors", "available_metrics")
