"""Telemetry Reading -- unified time-series storage for all metrics.

One table for all metric types (temperature, co2, relative_humidity, noise,
and any future metrics).  No per-metric tables or per-metric logic.

Replaces the legacy free-text floor/zone columns with proper foreign keys
to the locations and sensors tables.  Legacy columns are kept temporarily
for backward compatibility during migration.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Float,
    DateTime,
    ForeignKey,
    Index,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class TelemetryReading(Base):
    __tablename__ = "telemetry_readings"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        default=lambda: f"tr-{uuid.uuid4().hex[:12]}",
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False,
    )
    location_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("locations.id"), nullable=True,
        comment="Resolved room or placement location",
    )
    sensor_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("sensors.sensor_id"), nullable=True,
        comment="Resolved sensor, NULL for room/zone-level source data",
    )
    metric_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="temperature | co2 | relative_humidity | noise | custom",
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(
        String(20), nullable=False, default="",
        comment="C, ppm, %, dBA, etc.",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="When the sensor captured this reading",
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        comment="When the platform received this reading",
    )
    source_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="sensor | placement | room | zone | building",
    )
    aggregation_method: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="raw",
        comment="raw | avg | min | max | median",
    )
    quality_flag: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="good",
        comment="good | suspect | missing | stale | out_of_range",
    )
    connector_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Which endpoint provided this reading",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True,
    )

    # Legacy columns kept for backward compatibility during migration
    floor: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="LEGACY: Floor label",
    )
    zone: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="LEGACY: Zone label",
    )

    # Relationships
    location = relationship("Location", lazy="noload")
    sensor = relationship("Sensor", lazy="noload")

    __table_args__ = (
        Index(
            "ix_telemetry_building_metric_time",
            "building_id", "metric_type", "recorded_at",
        ),
        Index(
            "ix_telemetry_location_metric_time",
            "location_id", "metric_type", "recorded_at",
        ),
        Index(
            "ix_telemetry_sensor_time",
            "sensor_id", "recorded_at",
        ),
        Index(
            "ix_telemetry_building_location_time",
            "building_id", "location_id", "recorded_at",
        ),
        # Legacy index kept during migration
        Index(
            "ix_telemetry_building_floor_time",
            "building_id", "floor", "recorded_at",
        ),
    )

    def to_api_dict(self) -> dict:
        return {
            "id": self.id,
            "buildingId": self.building_id,
            "locationId": self.location_id,
            "sensorId": self.sensor_id,
            "metricType": self.metric_type,
            "value": self.value,
            "unit": self.unit,
            "recordedAt": self.recorded_at.isoformat(),
            "ingestedAt": self.ingested_at.isoformat(),
            "sourceLevel": self.source_level,
            "aggregationMethod": self.aggregation_method,
            "qualityFlag": self.quality_flag,
            "connectorId": self.connector_id,
            "metadata": self.metadata_,
            # Legacy fields
            "floor": self.floor,
            "zone": self.zone,
        }
