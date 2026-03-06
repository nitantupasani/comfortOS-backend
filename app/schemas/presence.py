"""Presence and notification schemas."""

from pydantic import BaseModel


class PresenceEventRequest(BaseModel):
    """Matches PresenceInfo.toJson() from the Flutter frontend."""
    buildingId: str
    method: str  # qr, wifi, ble, manual
    confidence: float = 0.5
    timestamp: str | None = None
    isVerified: bool = False


class BeaconResponse(BaseModel):
    id: str
    buildingId: str
    uuid: str
    major: int | None = None
    minor: int | None = None
    label: str | None = None


class PushTokenRegisterRequest(BaseModel):
    userId: str
    pushToken: str
    platform: str | None = None


class DatasetReadRequest(BaseModel):
    """Request to read an external dataset via the Connector Gateway."""
    buildingId: str
    datasetKey: str
    params: dict | None = None
