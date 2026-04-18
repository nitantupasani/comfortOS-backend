"""Pydantic schemas for the location hierarchy API."""

from pydantic import BaseModel, Field


class LocationCreate(BaseModel):
    buildingId: str
    parentId: str | None = None
    type: str = Field(..., description="building | block_or_wing | floor | room | placement")
    name: str
    code: str | None = None
    sortOrder: int = 0
    orientation: str | None = None
    usageType: str | None = None
    externalRefs: dict | None = None
    metadata: dict | None = None


class LocationUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    sortOrder: int | None = None
    orientation: str | None = None
    usageType: str | None = None
    externalRefs: dict | None = None
    metadata: dict | None = None


class LocationResponse(BaseModel):
    id: str
    buildingId: str
    parentId: str | None = None
    type: str
    name: str
    code: str | None = None
    sortOrder: int = 0
    orientation: str | None = None
    usageType: str | None = None
    externalRefs: dict | None = None
    metadata: dict | None = None
    createdAt: str
    updatedAt: str


class LocationTreeNode(BaseModel):
    """Recursive tree node for full hierarchy response."""
    id: str
    buildingId: str
    parentId: str | None = None
    type: str
    name: str
    code: str | None = None
    sortOrder: int = 0
    orientation: str | None = None
    usageType: str | None = None
    externalRefs: dict | None = None
    children: list["LocationTreeNode"] = []


class LocationBatchCreate(BaseModel):
    """Create multiple locations in one request (for initial building setup)."""
    buildingId: str
    locations: list[LocationCreate]
