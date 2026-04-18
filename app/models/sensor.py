"""Sensor model -- per-building sensor registry.

Each sensor is linked to exactly one room (via room_id) and optionally
to a placement within that room (via placement_id).  Multiple sensors
can exist in the same room, providing the same or different metrics.

Sensor configuration is building-specific and data-driven.  It is never
hardcoded in application logic.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Sensor(Base):
    __tablename__ = "sensors"

    sensor_id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        default=lambda: f"sens-{uuid.uuid4().hex[:8]}",
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True,
    )
    room_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("locations.id"), nullable=False,
        comment="FK to locations.id where type=room",
    )
    placement_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("locations.id"), nullable=True,
        comment="FK to locations.id where type=placement (optional sub-room position)",
    )
    zone_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("zones.id"), nullable=True,
        comment="Informational zone assignment",
    )
    sensor_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Device category: iaq_sensor, thermostat, sound_meter, multi_sensor, etc.",
    )
    metric_types: Mapped[list] = mapped_column(
        JSON, nullable=False,
        comment='Metric types this sensor provides, e.g. ["temperature", "relative_humidity"]',
    )
    source_endpoint_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("telemetry_endpoints.endpoint_id"), nullable=True,
        comment="Which endpoint provides data for this sensor",
    )
    source_identifier: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="External system identifier (BMS point name, device serial, etc.)",
    )
    unit_map: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment='Metric-to-unit map, e.g. {"temperature": "C", "relative_humidity": "%"}',
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Priority within room for same metric. Lower = higher priority.",
    )
    is_preferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="If true, this sensor is preferred for its metrics in this room",
    )
    aggregation_group: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Grouping key for multi-sensor aggregation: 'main', 'backup', etc.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    calibration_offset: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment='Per-metric calibration offsets, e.g. {"temperature": -0.3}',
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True,
        comment="Manufacturer, model, firmware, installation date, etc.",
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

    # Relationships
    building = relationship("Building", backref="sensors", lazy="noload")
    room = relationship(
        "Location", foreign_keys=[room_id], lazy="selectin",
    )
    placement = relationship(
        "Location", foreign_keys=[placement_id], lazy="selectin",
    )

    __table_args__ = (
        Index("ix_sensor_building_active", "building_id", "is_active"),
        Index("ix_sensor_room", "room_id", "is_active"),
        Index("ix_sensor_source_id", "source_identifier", "building_id", unique=True),
        Index("ix_sensor_endpoint", "source_endpoint_id"),
    )

    def to_api_dict(self) -> dict:
        return {
            "sensorId": self.sensor_id,
            "buildingId": self.building_id,
            "roomId": self.room_id,
            "placementId": self.placement_id,
            "zoneId": self.zone_id,
            "sensorType": self.sensor_type,
            "metricTypes": self.metric_types,
            "sourceEndpointId": self.source_endpoint_id,
            "sourceIdentifier": self.source_identifier,
            "unitMap": self.unit_map,
            "priority": self.priority,
            "isPreferred": self.is_preferred,
            "aggregationGroup": self.aggregation_group,
            "isActive": self.is_active,
            "calibrationOffset": self.calibration_offset,
            "metadata": self.metadata_,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
