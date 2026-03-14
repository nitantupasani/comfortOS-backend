"""Create building_connectors table.

Revision ID: 0004_building_connectors
Revises: 0003_telemetry_readings
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_building_connectors"
down_revision = "0003_telemetry_readings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "building_connectors",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("http_method", sa.String(10), nullable=False, server_default="GET"),
        sa.Column("request_headers", sa.JSON, nullable=True),
        sa.Column("request_body", sa.JSON, nullable=True),
        sa.Column("auth_type", sa.String(30), nullable=False, server_default="bearer_token"),
        sa.Column("auth_config", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("response_mapping", sa.JSON, nullable=True),
        sa.Column("available_metrics", sa.JSON, nullable=True),
        sa.Column("polling_interval_minutes", sa.Integer, nullable=False, server_default="15"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_polls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_readings_ingested", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_connector_building_enabled",
        "building_connectors",
        ["building_id", "is_enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_building_enabled", table_name="building_connectors")
    op.drop_table("building_connectors")
