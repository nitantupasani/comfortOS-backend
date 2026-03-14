"""Add telemetry_readings table for building sensor data.

Stores time-series environmental measurements (temperature, CO2, noise,
humidity) ingested from building service connectors.

Revision ID: 0003_telemetry_readings
Revises: 0002_drop_bldg_vote_limit
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_telemetry_readings"
down_revision = "0002_drop_bldg_vote_limit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_readings",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "building_id",
            sa.String(50),
            sa.ForeignKey("buildings.id"),
            nullable=False,
        ),
        sa.Column(
            "metric_type",
            sa.String(50),
            nullable=False,
            comment="temperature | co2 | noise | humidity | custom",
        ),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column(
            "unit",
            sa.String(20),
            nullable=False,
            server_default="",
            comment="°C, ppm, dBA, %, etc.",
        ),
        sa.Column(
            "floor",
            sa.String(100),
            nullable=True,
            comment="Floor label (optional)",
        ),
        sa.Column(
            "zone",
            sa.String(100),
            nullable=True,
            comment="Zone label (optional)",
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="When the sensor captured this reading",
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            comment="When the platform received this reading",
        ),
        sa.Column(
            "metadata",
            sa.JSON,
            nullable=True,
            comment="Arbitrary extra context (sensor_id, device, etc.)",
        ),
    )
    op.create_index(
        "ix_telemetry_building_metric_time",
        "telemetry_readings",
        ["building_id", "metric_type", "recorded_at"],
    )
    op.create_index(
        "ix_telemetry_building_floor_time",
        "telemetry_readings",
        ["building_id", "floor", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_building_floor_time", table_name="telemetry_readings")
    op.drop_index("ix_telemetry_building_metric_time", table_name="telemetry_readings")
    op.drop_table("telemetry_readings")
