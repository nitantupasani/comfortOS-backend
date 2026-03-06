"""Vote request/response schemas matching the Flutter Vote model."""

from datetime import datetime
from pydantic import BaseModel


class VoteSubmitRequest(BaseModel):
    """Matches Vote.toJson() from the Flutter frontend."""
    voteUuid: str
    buildingId: str
    userId: str
    payload: dict
    schemaVersion: int = 1
    createdAt: str | None = None
    status: str | None = None


class VoteSubmitResponse(BaseModel):
    status: str  # "accepted" | "already_accepted"
    voteUuid: str


class VoteHistoryItem(BaseModel):
    voteUuid: str
    buildingId: str
    userId: str
    payload: dict
    schemaVersion: int
    createdAt: str
    status: str
