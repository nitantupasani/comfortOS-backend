"""Telemetry Endpoint model -- building-level endpoint registry.

Each building can have one or many endpoints.  Each endpoint has its own
mode, authentication, zone scope, response format, and normalization profile.

Endpoint modes:
- single_zone:     one endpoint, one zone/room
- multi_zone:      one endpoint, multiple zones
- building_wide:   one endpoint, all zones
- sensor_centric:  one endpoint, raw sensor data
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class TelemetryEndpoint(Base):
    __tablename__ = "telemetry_endpoints"

    endpoint_id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        default=lambda: f"ep-{uuid.uuid4().hex[:8]}",
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True,
    )
    endpoint_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="Human-readable label, e.g. 'Siemens BMS Floor 1-3'",
    )
    endpoint_url: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="Full URL to poll",
    )

    # Authentication
    authentication_config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict,
        comment='Auth details: {"type": "api_key", "header": "X-Key", "api_key": "..."}',
    )

    # Endpoint mode
    endpoint_mode: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="single_zone | multi_zone | building_wide | sensor_centric",
    )

    # Scope declaration
    served_zone_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Zone IDs this endpoint covers",
    )
    served_room_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Room location IDs this endpoint covers",
    )
    served_sensor_ids: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Sensor IDs this endpoint covers (sensor_centric mode)",
    )
    default_location_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("locations.id"), nullable=True,
        comment="Default location for single_zone mode",
    )

    # Response mapping
    response_format: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="How to extract readings from the response body",
    )
    location_mapping: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Rules for resolving source location IDs to ComfortOS locations",
    )
    sensor_mapping: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Rules for resolving source sensor IDs to ComfortOS sensors",
    )
    normalization_profile: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Per-endpoint overrides: metric_type_map, unit_map, timestamp_format, etc.",
    )
    available_metrics: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment='Metric types provided, e.g. ["temperature", "co2"]',
    )

    # HTTP config
    http_method: Mapped[str] = mapped_column(
        String(10), nullable=False, default="GET",
    )
    request_headers: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    request_body: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )

    # Polling config
    polling_config: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        default=lambda: {
            "interval_minutes": 15,
            "timeout_seconds": 30,
            "retry_count": 3,
            "backoff_strategy": "exponential",
        },
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Endpoint priority. Lower = higher priority.",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    # Status tracking
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="success | error | timeout",
    )
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    total_polls: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    total_readings_ingested: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # Timestamps
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
    building = relationship("Building", backref="telemetry_endpoints", lazy="noload")

    VALID_MODES = {"single_zone", "multi_zone", "building_wide", "sensor_centric"}

    __table_args__ = (
        Index("ix_endpoint_building_enabled", "building_id", "is_enabled"),
    )

    def to_api_dict(self, *, mask_secrets: bool = True) -> dict:
        return {
            "endpointId": self.endpoint_id,
            "buildingId": self.building_id,
            "endpointName": self.endpoint_name,
            "endpointUrl": self.endpoint_url,
            "authenticationConfig": self._masked_auth() if mask_secrets else self.authentication_config,
            "endpointMode": self.endpoint_mode,
            "servedZoneIds": self.served_zone_ids,
            "servedRoomIds": self.served_room_ids,
            "servedSensorIds": self.served_sensor_ids,
            "defaultLocationId": self.default_location_id,
            "responseFormat": self.response_format,
            "locationMapping": self.location_mapping,
            "sensorMapping": self.sensor_mapping,
            "normalizationProfile": self.normalization_profile,
            "availableMetrics": self.available_metrics,
            "httpMethod": self.http_method,
            "pollingConfig": self.polling_config,
            "priority": self.priority,
            "isEnabled": self.is_enabled,
            "lastPolledAt": self.last_polled_at.isoformat() if self.last_polled_at else None,
            "lastStatus": self.last_status,
            "lastError": self.last_error,
            "consecutiveFailures": self.consecutive_failures,
            "totalPolls": self.total_polls,
            "totalReadingsIngested": self.total_readings_ingested,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }

    def _masked_auth(self) -> dict:
        if not self.authentication_config:
            return {}
        masked = dict(self.authentication_config)
        for k in ("token", "client_secret", "password", "api_key", "secret"):
            if k in masked and masked[k]:
                masked[k] = "******"
        return masked
