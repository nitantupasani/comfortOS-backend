"""Pydantic schemas for the sensor registry API."""

from pydantic import BaseModel, Field


class SensorCreate(BaseModel):
    buildingId: str
    roomId: str
    placementId: str | None = None
    zoneId: str | None = None
    sensorType: str | None = None
    metricTypes: list[str] = Field(..., min_length=1)
    sourceEndpointId: str | None = None
    sourceIdentifier: str | None = None
    unitMap: dict | None = None
    priority: int = 0
    isPreferred: bool = False
    aggregationGroup: str | None = None
    calibrationOffset: dict | None = None
    metadata: dict | None = None


class SensorUpdate(BaseModel):
    roomId: str | None = None
    placementId: str | None = None
    zoneId: str | None = None
    sensorType: str | None = None
    metricTypes: list[str] | None = None
    sourceEndpointId: str | None = None
    sourceIdentifier: str | None = None
    unitMap: dict | None = None
    priority: int | None = None
    isPreferred: bool | None = None
    aggregationGroup: str | None = None
    isActive: bool | None = None
    calibrationOffset: dict | None = None
    metadata: dict | None = None


class SensorResponse(BaseModel):
    sensorId: str
    buildingId: str
    roomId: str
    placementId: str | None = None
    zoneId: str | None = None
    sensorType: str | None = None
    metricTypes: list[str]
    sourceEndpointId: str | None = None
    sourceIdentifier: str | None = None
    unitMap: dict | None = None
    priority: int = 0
    isPreferred: bool = False
    aggregationGroup: str | None = None
    isActive: bool = True
    calibrationOffset: dict | None = None
    metadata: dict | None = None
    createdAt: str
    updatedAt: str
