"""Pydantic schemas for telemetry ingestion and query API.

Supports both the new normalized model (location_id, sensor_id) and
legacy compatibility (floor, zone strings).
"""

from datetime import datetime
from pydantic import BaseModel, Field


# -- Ingestion (push mode) ------------------------------------------------

class TelemetryReadingIn(BaseModel):
    """A single sensor reading pushed by a building service.

    Minimum required fields: metric_type, value, recorded_at, location_ref.
    Everything else is optional and will be inferred by the normalization
    pipeline if not provided.
    """
    metricType: str = Field(..., description="temperature | co2 | relative_humidity | noise | custom")
    value: float
    unit: str | None = None
    recordedAt: datetime
    locationRef: str | None = Field(
        None,
        description="Matched against locations.external_refs, locations.name, or locations.id",
    )
    sensorRef: str | None = Field(
        None,
        description="Matched against sensors.source_identifier or sensors.sensor_id",
    )
    sourceLevel: str | None = None
    aggregationMethod: str | None = None
    qualityFlag: str | None = None
    metadata: dict | None = None

    # Legacy fields for backward compatibility
    floor: str | None = None
    zone: str | None = None


class TelemetryBatchRequest(BaseModel):
    """Batch push of sensor readings for a building."""
    buildingId: str
    readings: list[TelemetryReadingIn] = Field(..., min_length=1, max_length=1000)


class TelemetryBatchResponse(BaseModel):
    accepted: int
    rejected: int = 0
    buildingId: str
    errors: list[dict] = []


# -- Query -----------------------------------------------------------------

class TelemetryPoint(BaseModel):
    """A single point in a time-series response."""
    recordedAt: str
    value: float
    locationId: str | None = None
    sensorId: str | None = None
    qualityFlag: str | None = None
    # Legacy
    floor: str | None = None
    zone: str | None = None


class TelemetrySeriesGroup(BaseModel):
    """A group of readings sharing the same location key."""
    label: str
    locationId: str | None = None
    locationName: str | None = None
    locationType: str | None = None
    zones: list[str] = []
    points: list[TelemetryPoint]
    # Legacy
    floor: str | None = None
    zone: str | None = None


class TelemetryQueryResponse(BaseModel):
    """Response for a time-series telemetry query."""
    buildingId: str
    metricType: str
    unit: str
    granularity: str
    series: list[TelemetrySeriesGroup]


class TelemetryRoomSummary(BaseModel):
    """Aggregated room-level metric summary."""
    locationId: str
    locationName: str
    locationType: str
    metricType: str
    value: float
    unit: str
    recordedAt: str
    aggregationMethod: str
    sensorCount: int
    qualityFlag: str
    isStale: bool = False


class BuildingTelemetryConfigIn(BaseModel):
    """Create or update a building telemetry config entry."""
    buildingId: str
    metricType: str
    isEnabled: bool = True
    defaultUnit: str | None = None
    sourceLevel: str | None = None
    roomAggregationRule: str = "avg"
    preferredSensorId: str | None = None
    validRangeMin: float | None = None
    validRangeMax: float | None = None
    staleThresholdMinutes: int | None = None
    conflictResolution: str = "newest_wins"
    connectorPriority: list[str] | None = None
    metadata: dict | None = None
