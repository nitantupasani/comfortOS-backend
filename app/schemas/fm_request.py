"""FM role request schemas."""

from pydantic import BaseModel


class FMRequestCreate(BaseModel):
    """Submit a request to become an FM for a building."""
    buildingId: str
    roleRequested: str = "building_facility_manager"
    message: str | None = None


class FMRequestResponse(BaseModel):
    """FM request visible to users and admins."""
    id: str
    userId: str
    userEmail: str
    userName: str
    buildingId: str
    buildingName: str
    roleRequested: str
    message: str | None = None
    status: str
    reviewedBy: str | None = None
    reviewNote: str | None = None
    createdAt: str
    reviewedAt: str | None = None


class FMRequestReview(BaseModel):
    """Admin reviews (approves/rejects) a request."""
    action: str  # "approve" | "reject"
    reviewNote: str | None = None
