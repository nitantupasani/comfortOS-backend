"""Pydantic schemas for the zone API."""

from pydantic import BaseModel


class ZoneCreate(BaseModel):
    buildingId: str
    name: str
    zoneType: str | None = None
    externalRefs: dict | None = None
    metadata: dict | None = None
    memberLocationIds: list[str] | None = None


class ZoneUpdate(BaseModel):
    name: str | None = None
    zoneType: str | None = None
    externalRefs: dict | None = None
    metadata: dict | None = None


class ZoneMemberAdd(BaseModel):
    locationIds: list[str]


class ZoneResponse(BaseModel):
    id: str
    buildingId: str
    name: str
    zoneType: str | None = None
    externalRefs: dict | None = None
    metadata: dict | None = None
    createdAt: str
    members: list[dict] = []
