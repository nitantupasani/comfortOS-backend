"""Add Building 28 and its telemetry config.

Revision ID: 0008_add_building_28
Revises: 0007_fix_weekday_alignment
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0008_add_building_28"
down_revision = "0007_fix_weekday_alignment"
branch_labels = None
depends_on = None

BUILDING_ID = "bldg-28"
CONFIG_ID = f"cfg-{uuid.uuid4().hex[:8]}"
API_KEY = "building28-telemetry-api-key-2026"


def upgrade() -> None:
    # Create building
    op.execute(
        sa.text(
            "INSERT INTO buildings (id, name, address, city, requires_access_permission, created_at) "
            "VALUES (:id, :name, :address, :city, :rap, NOW())"
        ).bindparams(
            id=BUILDING_ID,
            name="Building 28",
            address="The Hague University of Applied Sciences, Building 28",
            city="The Hague",
            rap=False,
        )
    )

    # Create building config with telemetry API key
    op.execute(
        sa.text(
            "INSERT INTO building_configs (id, building_id, schema_version, dashboard_layout, is_active, created_at, updated_at) "
            "VALUES (:id, :building_id, :schema_version, CAST(:dashboard_layout AS jsonb), :is_active, NOW(), NOW())"
        ).bindparams(
            sa.bindparam("dashboard_layout", type_=sa.Text),
            id=CONFIG_ID,
            building_id=BUILDING_ID,
            schema_version=1,
            dashboard_layout=f'{{"telemetryApiKey": "{API_KEY}"}}',
            is_active=True,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM building_configs WHERE building_id = :id").bindparams(id=BUILDING_ID)
    )
    op.execute(
        sa.text("DELETE FROM buildings WHERE id = :id").bindparams(id=BUILDING_ID)
    )
