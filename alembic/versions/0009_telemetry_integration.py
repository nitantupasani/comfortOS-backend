"""Add telemetry integration tables and columns.

Revision ID: 0009_telemetry_integration
Revises: 0008_add_building_28
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_telemetry_integration"
down_revision = "0008_add_building_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Create tables using IF NOT EXISTS ────────────────────

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS locations (
            id VARCHAR(50) PRIMARY KEY,
            building_id VARCHAR(50) NOT NULL REFERENCES buildings(id),
            parent_id VARCHAR(50) REFERENCES locations(id),
            type VARCHAR(20) NOT NULL,
            name VARCHAR(200) NOT NULL,
            code VARCHAR(50),
            sort_order INTEGER NOT NULL DEFAULT 0,
            orientation VARCHAR(50),
            usage_type VARCHAR(50),
            external_refs JSON,
            metadata JSON,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS zones (
            id VARCHAR(50) PRIMARY KEY,
            building_id VARCHAR(50) NOT NULL REFERENCES buildings(id),
            name VARCHAR(200) NOT NULL,
            zone_type VARCHAR(50),
            external_refs JSON,
            metadata JSON,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS zone_members (
            zone_id VARCHAR(50) REFERENCES zones(id) ON DELETE CASCADE,
            location_id VARCHAR(50) REFERENCES locations(id),
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (zone_id, location_id)
        )
    """))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS telemetry_endpoints (
            endpoint_id VARCHAR(50) PRIMARY KEY,
            building_id VARCHAR(50) NOT NULL REFERENCES buildings(id),
            endpoint_name VARCHAR(200) NOT NULL,
            endpoint_url VARCHAR(500) NOT NULL,
            authentication_config JSON NOT NULL DEFAULT '{}',
            endpoint_mode VARCHAR(30) NOT NULL,
            served_zone_ids JSON,
            served_room_ids JSON,
            served_sensor_ids JSON,
            default_location_id VARCHAR(50) REFERENCES locations(id),
            response_format JSON,
            location_mapping JSON,
            sensor_mapping JSON,
            normalization_profile JSON,
            available_metrics JSON,
            http_method VARCHAR(10) NOT NULL DEFAULT 'GET',
            request_headers JSON,
            request_body JSON,
            polling_config JSON NOT NULL DEFAULT '{"interval_minutes":15}',
            priority INTEGER NOT NULL DEFAULT 0,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            last_polled_at TIMESTAMPTZ,
            last_status VARCHAR(20),
            last_error TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            total_polls INTEGER NOT NULL DEFAULT 0,
            total_readings_ingested INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS sensors (
            sensor_id VARCHAR(50) PRIMARY KEY,
            building_id VARCHAR(50) NOT NULL REFERENCES buildings(id),
            room_id VARCHAR(50) NOT NULL REFERENCES locations(id),
            placement_id VARCHAR(50) REFERENCES locations(id),
            zone_id VARCHAR(50) REFERENCES zones(id),
            sensor_type VARCHAR(50),
            metric_types JSON NOT NULL,
            source_endpoint_id VARCHAR(50) REFERENCES telemetry_endpoints(endpoint_id),
            source_identifier VARCHAR(200),
            unit_map JSON,
            priority INTEGER NOT NULL DEFAULT 0,
            is_preferred BOOLEAN NOT NULL DEFAULT false,
            aggregation_group VARCHAR(50),
            is_active BOOLEAN NOT NULL DEFAULT true,
            calibration_offset JSON,
            metadata JSON,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS building_telemetry_config (
            id VARCHAR(50) PRIMARY KEY,
            building_id VARCHAR(50) NOT NULL REFERENCES buildings(id),
            metric_type VARCHAR(50) NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            default_unit VARCHAR(20),
            source_level VARCHAR(20),
            room_aggregation_rule VARCHAR(20) NOT NULL DEFAULT 'avg',
            preferred_sensor_id VARCHAR(50) REFERENCES sensors(sensor_id),
            valid_range_min FLOAT,
            valid_range_max FLOAT,
            stale_threshold_minutes INTEGER,
            conflict_resolution VARCHAR(20) NOT NULL DEFAULT 'newest_wins',
            connector_priority JSON,
            metadata JSON,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    # ── Add columns to telemetry_readings (skip if exist) ────

    for col, typedef in [
        ("location_id", "VARCHAR(50)"),
        ("sensor_id", "VARCHAR(50)"),
        ("source_level", "VARCHAR(20)"),
        ("aggregation_method", "VARCHAR(20) DEFAULT 'raw'"),
        ("quality_flag", "VARCHAR(20) DEFAULT 'good'"),
        ("connector_id", "VARCHAR(50)"),
    ]:
        conn.execute(sa.text(f"""
            DO $$ BEGIN
                ALTER TABLE telemetry_readings ADD COLUMN {col} {typedef};
            EXCEPTION WHEN duplicate_column THEN
                NULL;
            END $$
        """))

    # ── Create indexes (skip if exist) ───────────────────────

    for idx, table, cols in [
        ("ix_location_building_type", "locations", "building_id, type"),
        ("ix_location_building_parent", "locations", "building_id, parent_id"),
        ("ix_locations_parent_id", "locations", "parent_id"),
        ("ix_locations_building_id", "locations", "building_id"),
        ("ix_zones_building_id", "zones", "building_id"),
        ("ix_zone_member_location", "zone_members", "location_id"),
        ("ix_endpoint_building_enabled", "telemetry_endpoints", "building_id, is_enabled"),
        ("ix_sensor_building_active", "sensors", "building_id, is_active"),
        ("ix_sensor_room", "sensors", "room_id, is_active"),
        ("ix_sensor_endpoint", "sensors", "source_endpoint_id"),
        ("ix_telemetry_location_metric_time", "telemetry_readings", "location_id, metric_type, recorded_at"),
        ("ix_telemetry_sensor_time", "telemetry_readings", "sensor_id, recorded_at"),
        ("ix_telemetry_building_location_time", "telemetry_readings", "building_id, location_id, recorded_at"),
    ]:
        conn.execute(sa.text(
            f"CREATE INDEX IF NOT EXISTS {idx} ON {table} ({cols})"
        ))

    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_sensor_source_id ON sensors (source_identifier, building_id)"
    ))


def downgrade() -> None:
    op.drop_index("ix_telemetry_building_location_time", table_name="telemetry_readings")
    op.drop_index("ix_telemetry_sensor_time", table_name="telemetry_readings")
    op.drop_index("ix_telemetry_location_metric_time", table_name="telemetry_readings")
    op.drop_column("telemetry_readings", "connector_id")
    op.drop_column("telemetry_readings", "quality_flag")
    op.drop_column("telemetry_readings", "aggregation_method")
    op.drop_column("telemetry_readings", "source_level")
    op.drop_column("telemetry_readings", "sensor_id")
    op.drop_column("telemetry_readings", "location_id")
    op.drop_table("building_telemetry_config")
    op.drop_table("sensors")
    op.drop_table("telemetry_endpoints")
    op.drop_table("zone_members")
    op.drop_table("zones")
    op.drop_table("locations")
