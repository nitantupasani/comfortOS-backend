"""Add telemetry integration tables and columns.

Creates new tables: locations, zones, zone_members, telemetry_endpoints,
sensors, building_telemetry_config.

Adds new columns to telemetry_readings: location_id, sensor_id,
source_level, aggregation_method, quality_flag, connector_id.

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
    # ── locations ────────────────────────────────────────────
    op.create_table(
        "locations",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("parent_id", sa.String(50), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("orientation", sa.String(50), nullable=True),
        sa.Column("usage_type", sa.String(50), nullable=True),
        sa.Column("external_refs", sa.JSON, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_location_building_type", "locations", ["building_id", "type"])
    op.create_index("ix_location_building_parent", "locations", ["building_id", "parent_id"])
    op.create_index("ix_locations_parent_id", "locations", ["parent_id"])
    op.create_index("ix_locations_building_id", "locations", ["building_id"])

    # ── zones ────────────────────────────────────────────────
    op.create_table(
        "zones",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("zone_type", sa.String(50), nullable=True),
        sa.Column("external_refs", sa.JSON, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_zones_building_id", "zones", ["building_id"])

    # ── zone_members ─────────────────────────────────────────
    op.create_table(
        "zone_members",
        sa.Column("zone_id", sa.String(50), sa.ForeignKey("zones.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("location_id", sa.String(50), sa.ForeignKey("locations.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_zone_member_location", "zone_members", ["location_id"])

    # ── telemetry_endpoints ──────────────────────────────────
    op.create_table(
        "telemetry_endpoints",
        sa.Column("endpoint_id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("endpoint_name", sa.String(200), nullable=False),
        sa.Column("endpoint_url", sa.String(500), nullable=False),
        sa.Column("authentication_config", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("endpoint_mode", sa.String(30), nullable=False),
        sa.Column("served_zone_ids", sa.JSON, nullable=True),
        sa.Column("served_room_ids", sa.JSON, nullable=True),
        sa.Column("served_sensor_ids", sa.JSON, nullable=True),
        sa.Column("default_location_id", sa.String(50), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column("response_format", sa.JSON, nullable=True),
        sa.Column("location_mapping", sa.JSON, nullable=True),
        sa.Column("sensor_mapping", sa.JSON, nullable=True),
        sa.Column("normalization_profile", sa.JSON, nullable=True),
        sa.Column("available_metrics", sa.JSON, nullable=True),
        sa.Column("http_method", sa.String(10), nullable=False, server_default="GET"),
        sa.Column("request_headers", sa.JSON, nullable=True),
        sa.Column("request_body", sa.JSON, nullable=True),
        sa.Column("polling_config", sa.JSON, nullable=False, server_default='{"interval_minutes":15,"timeout_seconds":30,"retry_count":3,"backoff_strategy":"exponential"}'),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_polls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_readings_ingested", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_endpoint_building_enabled", "telemetry_endpoints", ["building_id", "is_enabled"])

    # ── sensors ──────────────────────────────────────────────
    op.create_table(
        "sensors",
        sa.Column("sensor_id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("room_id", sa.String(50), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("placement_id", sa.String(50), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column("zone_id", sa.String(50), sa.ForeignKey("zones.id"), nullable=True),
        sa.Column("sensor_type", sa.String(50), nullable=True),
        sa.Column("metric_types", sa.JSON, nullable=False),
        sa.Column("source_endpoint_id", sa.String(50), sa.ForeignKey("telemetry_endpoints.endpoint_id"), nullable=True),
        sa.Column("source_identifier", sa.String(200), nullable=True),
        sa.Column("unit_map", sa.JSON, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_preferred", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("aggregation_group", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("calibration_offset", sa.JSON, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sensor_building_active", "sensors", ["building_id", "is_active"])
    op.create_index("ix_sensor_room", "sensors", ["room_id", "is_active"])
    op.create_index("ix_sensor_source_id", "sensors", ["source_identifier", "building_id"], unique=True)
    op.create_index("ix_sensor_endpoint", "sensors", ["source_endpoint_id"])

    # ── building_telemetry_config ────────────────────────────
    op.create_table(
        "building_telemetry_config",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("metric_type", sa.String(50), nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("default_unit", sa.String(20), nullable=True),
        sa.Column("source_level", sa.String(20), nullable=True),
        sa.Column("room_aggregation_rule", sa.String(20), nullable=False, server_default="avg"),
        sa.Column("preferred_sensor_id", sa.String(50), sa.ForeignKey("sensors.sensor_id"), nullable=True),
        sa.Column("valid_range_min", sa.Float, nullable=True),
        sa.Column("valid_range_max", sa.Float, nullable=True),
        sa.Column("stale_threshold_minutes", sa.Integer, nullable=True),
        sa.Column("conflict_resolution", sa.String(20), nullable=False, server_default="newest_wins"),
        sa.Column("connector_priority", sa.JSON, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Add new columns to telemetry_readings ────────────────
    op.add_column("telemetry_readings",
        sa.Column("location_id", sa.String(50), nullable=True))
    op.add_column("telemetry_readings",
        sa.Column("sensor_id", sa.String(50), nullable=True))
    op.add_column("telemetry_readings",
        sa.Column("source_level", sa.String(20), nullable=True))
    op.add_column("telemetry_readings",
        sa.Column("aggregation_method", sa.String(20), nullable=True, server_default="raw"))
    op.add_column("telemetry_readings",
        sa.Column("quality_flag", sa.String(20), nullable=True, server_default="good"))
    op.add_column("telemetry_readings",
        sa.Column("connector_id", sa.String(50), nullable=True))

    # Indexes on new columns
    op.create_index("ix_telemetry_location_metric_time",
        "telemetry_readings", ["location_id", "metric_type", "recorded_at"])
    op.create_index("ix_telemetry_sensor_time",
        "telemetry_readings", ["sensor_id", "recorded_at"])
    op.create_index("ix_telemetry_building_location_time",
        "telemetry_readings", ["building_id", "location_id", "recorded_at"])


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
