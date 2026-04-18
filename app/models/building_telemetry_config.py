"""Building Telemetry Config -- per-building, per-metric configuration.

Controls how each metric type is aggregated, validated, and resolved
when multiple sensors or endpoints provide it.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class BuildingTelemetryConfig(Base):
    __tablename__ = "building_telemetry_config"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        default=lambda: f"btc-{uuid.uuid4().hex[:8]}",
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False,
    )
    metric_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="temperature | co2 | relative_humidity | noise | custom",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    default_unit: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Inferred unit when missing from reading",
    )
    source_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="Expected source granularity: sensor | placement | room | zone | building",
    )
    room_aggregation_rule: Mapped[str] = mapped_column(
        String(20), nullable=False, default="avg",
        comment="avg | min | max | median | preferred_sensor",
    )
    preferred_sensor_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("sensors.sensor_id"), nullable=True,
    )
    valid_range_min: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Values below this are flagged out_of_range",
    )
    valid_range_max: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Values above this are flagged out_of_range",
    )
    stale_threshold_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="No reading within this window = stale",
    )
    conflict_resolution: Mapped[str] = mapped_column(
        String(20), nullable=False, default="newest_wins",
        comment="newest_wins | connector_priority | average",
    )
    connector_priority: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Ordered list of endpoint IDs for connector_priority resolution",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    building = relationship("Building", backref="telemetry_configs", lazy="noload")

    __table_args__ = (
        # One config row per (building, metric_type)
        {"comment": "Unique constraint on (building_id, metric_type)"},
    )

    # Default units per known metric type
    DEFAULT_UNITS = {
        "temperature": "C",
        "co2": "ppm",
        "relative_humidity": "%",
        "noise": "dBA",
        "voc": "ppb",
        "pm25": "ug/m3",
        "illuminance": "lux",
        "occupancy": "count",
        "setpoint": "C",
    }

    def to_api_dict(self) -> dict:
        return {
            "id": self.id,
            "buildingId": self.building_id,
            "metricType": self.metric_type,
            "isEnabled": self.is_enabled,
            "defaultUnit": self.default_unit,
            "sourceLevel": self.source_level,
            "roomAggregationRule": self.room_aggregation_rule,
            "preferredSensorId": self.preferred_sensor_id,
            "validRangeMin": self.valid_range_min,
            "validRangeMax": self.valid_range_max,
            "staleThresholdMinutes": self.stale_threshold_minutes,
            "conflictResolution": self.conflict_resolution,
            "connectorPriority": self.connector_priority,
            "metadata": self.metadata_,
        }
