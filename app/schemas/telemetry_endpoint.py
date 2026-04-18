"""Pydantic schemas for the telemetry endpoint registry API."""

from pydantic import BaseModel, Field


class EndpointCreate(BaseModel):
    buildingId: str
    endpointName: str
    endpointUrl: str
    authenticationConfig: dict = Field(default_factory=dict)
    endpointMode: str = Field(
        ..., description="single_zone | multi_zone | building_wide | sensor_centric",
    )
    servedZoneIds: list[str] | None = None
    servedRoomIds: list[str] | None = None
    servedSensorIds: list[str] | None = None
    defaultLocationId: str | None = None
    responseFormat: dict | None = None
    locationMapping: dict | None = None
    sensorMapping: dict | None = None
    normalizationProfile: dict | None = None
    availableMetrics: list[str] | None = None
    httpMethod: str = "GET"
    requestHeaders: dict | None = None
    requestBody: dict | None = None
    pollingConfig: dict = Field(
        default_factory=lambda: {
            "interval_minutes": 15,
            "timeout_seconds": 30,
            "retry_count": 3,
            "backoff_strategy": "exponential",
        },
    )
    priority: int = 0
    isEnabled: bool = True


class EndpointUpdate(BaseModel):
    endpointName: str | None = None
    endpointUrl: str | None = None
    authenticationConfig: dict | None = None
    endpointMode: str | None = None
    servedZoneIds: list[str] | None = None
    servedRoomIds: list[str] | None = None
    servedSensorIds: list[str] | None = None
    defaultLocationId: str | None = None
    responseFormat: dict | None = None
    locationMapping: dict | None = None
    sensorMapping: dict | None = None
    normalizationProfile: dict | None = None
    availableMetrics: list[str] | None = None
    httpMethod: str | None = None
    requestHeaders: dict | None = None
    requestBody: dict | None = None
    pollingConfig: dict | None = None
    priority: int | None = None
    isEnabled: bool | None = None


class EndpointResponse(BaseModel):
    endpointId: str
    buildingId: str
    endpointName: str
    endpointUrl: str
    authenticationConfig: dict
    endpointMode: str
    servedZoneIds: list[str] | None = None
    servedRoomIds: list[str] | None = None
    servedSensorIds: list[str] | None = None
    defaultLocationId: str | None = None
    responseFormat: dict | None = None
    locationMapping: dict | None = None
    sensorMapping: dict | None = None
    normalizationProfile: dict | None = None
    availableMetrics: list[str] | None = None
    httpMethod: str
    pollingConfig: dict
    priority: int
    isEnabled: bool
    lastPolledAt: str | None = None
    lastStatus: str | None = None
    consecutiveFailures: int = 0
    totalPolls: int = 0
    totalReadingsIngested: int = 0
    createdAt: str
    updatedAt: str


class EndpointTestResult(BaseModel):
    success: bool
    readingsFound: int = 0
    sampleReadings: list[dict] = []
    error: str | None = None
