"""Pydantic schemas for telemetry ingestion & query API."""

from datetime import datetime
from pydantic import BaseModel, Field


# ── Ingestion ──────────────────────────────────────────────────────────────

class TelemetryReadingIn(BaseModel):
    """A single sensor reading pushed by a building service."""
    metricType: str = Field(..., description="temperature | co2 | noise | humidity")
    value: float
    unit: str = Field("", description="°C, ppm, dBA, %")
    floor: str | None = None
    zone: str | None = None
    recordedAt: datetime
    metadata: dict | None = None


class TelemetryBatchRequest(BaseModel):
    """Batch push of sensor readings for a building."""
    buildingId: str
    readings: list[TelemetryReadingIn] = Field(..., min_length=1, max_length=1000)


class TelemetryBatchResponse(BaseModel):
    accepted: int
    buildingId: str


# ── Query ──────────────────────────────────────────────────────────────────

class TelemetryPoint(BaseModel):
    """A single point in a time-series response."""
    recordedAt: str
    value: float
    floor: str | None = None
    zone: str | None = None


class TelemetrySeriesGroup(BaseModel):
    """A group of readings sharing the same floor/zone key."""
    label: str  # e.g. "Floor 0", "Zone A", or "Building"
    floor: str | None = None
    zone: str | None = None
    points: list[TelemetryPoint]


class TelemetryQueryResponse(BaseModel):
    """Response for a time-series telemetry query."""
    buildingId: str
    metricType: str
    unit: str
    granularity: str  # "raw" | "hourly" | "daily"
    series: list[TelemetrySeriesGroup]
