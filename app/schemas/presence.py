"""Presence and notification schemas."""

from pydantic import BaseModel, Field


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


class SendNotificationRequest(BaseModel):
    """Request to send a push notification via FCM/APNs."""
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=1000)
    userIds: list[str] | None = Field(
        default=None,
        description="Target user IDs. If omitted, broadcasts to all registered devices.",
    )
    data: dict[str, str] | None = Field(
        default=None,
        description="Custom key/value payload delivered alongside the notification.",
    )


class SendNotificationResponse(BaseModel):
    status: str
    sent: int
    failed: int
    detail: str | None = None


class DatasetReadRequest(BaseModel):
    """Request to read an external dataset via the Connector Gateway."""
    buildingId: str
    datasetKey: str
    params: dict | None = None
