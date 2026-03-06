"""Tenant-related Pydantic schemas."""

from pydantic import BaseModel


class TenantResponse(BaseModel):
    """Public tenant info returned to clients."""
    id: str
    name: str
    emailDomain: str | None = None
    authProvider: str | None = None


class TenantCreateRequest(BaseModel):
    """Create a new tenant (admin only)."""
    name: str
    emailDomain: str | None = None
    authProvider: str | None = None


class BuildingTenantResponse(BaseModel):
    """A tenant's presence inside a specific building."""
    id: str
    buildingId: str
    tenantId: str
    tenantName: str | None = None
    floors: dict | list | None = None
    zones: dict | list | None = None
    isActive: bool = True


class BuildingTenantCreateRequest(BaseModel):
    """Assign a tenant to a building with location info."""
    buildingId: str
    tenantId: str
    floors: dict | list | None = None
    zones: dict | list | None = None


class OccupantOnboardRequest(BaseModel):
    """Register an occupant.

    Two flows are supported:

    1. **Domain-matched** — if the e-mail domain matches a tenant’s
       ``email_domain`` the user is auto-assigned to that tenant.
    2. **Independent** — if no tenant matches the domain the user is
       created *without* a tenant and can only access open buildings.
    """
    email: str
    name: str
    password: str
    buildingIds: list[str] | None = None


class OccupantOnboardResponse(BaseModel):
    status: str  # "onboarded" | "already_exists"
    userId: str | None = None
    tenantId: str | None = None


class UserBuildingAccessGrantRequest(BaseModel):
    """Grant a user access to a building (FM / admin only)."""
    userId: str
    buildingId: str


class UserBuildingAccessRevokeRequest(BaseModel):
    """Revoke a user's access to a building."""
    userId: str
    buildingId: str


class UserBuildingAccessResponse(BaseModel):
    """An explicit building access grant for a user."""
    id: str
    userId: str
    buildingId: str
    grantedBy: str | None = None
    isActive: bool = True
    createdAt: str | None = None
