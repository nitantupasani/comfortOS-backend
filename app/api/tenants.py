"""
Tenant & BuildingTenant management + occupant self-onboarding API routes.

    GET    /tenants                    → List tenants (admin)
    POST   /tenants                    → Create tenant (admin)
    GET    /tenants/{id}               → Get tenant detail
    POST   /tenants/onboard            → Self-onboard occupant via email domain
    GET    /building-tenants            → List building-tenant mappings
    POST   /building-tenants            → Assign tenant to building (admin / building FM)
    GET    /building-tenants/{id}       → Get single building-tenant mapping
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user, require_role
from ..models.user import User, UserRole
from ..models.tenant import Tenant
from ..models.building import Building
from ..models.building_tenant import BuildingTenant
from ..models.user_building_access import UserBuildingAccess
from ..schemas.tenant import (
    TenantResponse,
    TenantCreateRequest,
    BuildingTenantResponse,
    BuildingTenantCreateRequest,
    OccupantOnboardRequest,
    OccupantOnboardResponse,
    UserBuildingAccessGrantRequest,
    UserBuildingAccessResponse,
)
from ..services.auth_service import hash_password

router = APIRouter(tags=["tenants"])


# ── Tenants CRUD ─────────────────────────────────────────────────────────


@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all tenants (admin only)."""
    result = await db.execute(select(Tenant))
    tenants = result.scalars().all()
    return [
        TenantResponse(
            id=t.id,
            name=t.name,
            emailDomain=t.email_domain,
            authProvider=t.auth_provider,
        )
        for t in tenants
    ]


@router.post("/tenants", response_model=TenantResponse, status_code=201)
async def create_tenant(
    body: TenantCreateRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new tenant organisation (admin only)."""
    tenant = Tenant(
        name=body.name,
        email_domain=body.emailDomain,
        auth_provider=body.authProvider,
    )
    db.add(tenant)
    await db.flush()
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        emailDomain=tenant.email_domain,
        authProvider=tenant.auth_provider,
    )


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get tenant info. Non-admin users can only view their own tenant."""
    if user.role != UserRole.admin and (not user.tenant_id or user.tenant_id != tenant_id):
        raise HTTPException(status_code=403, detail="Tenant isolation violation")

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        emailDomain=tenant.email_domain,
        authProvider=tenant.auth_provider,
    )


# ── Occupant self-onboarding ────────────────────────────────────────────


@router.post("/tenants/onboard", response_model=OccupantOnboardResponse)
async def onboard_occupant(
    body: OccupantOnboardRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new occupant.  No JWT required (public endpoint).

    Two flows
    ---------
    1. **Domain-matched** — if the user's email domain matches a tenant's
       ``email_domain`` the account is automatically assigned to that tenant.
    2. **Independent** — if no tenant matches, the user is created *without*
       a tenant.  They can only access open buildings (those with
       ``requires_access_permission=False``).
    """
    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        return OccupantOnboardResponse(status="already_exists")

    # Extract domain from email
    if "@" not in body.email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    domain = body.email.rsplit("@", 1)[1].lower()

    # Try to find a tenant by email domain
    result = await db.execute(
        select(Tenant).where(Tenant.email_domain == domain)
    )
    tenant = result.scalar_one_or_none()

    tenant_id: str | None = tenant.id if tenant else None

    new_user = User(
        email=body.email,
        name=body.name,
        hashed_password=hash_password(body.password),
        role=UserRole.occupant,
        tenant_id=tenant_id,
        claims={"scopes": ["vote", "view_dashboard"]},
    )
    db.add(new_user)
    await db.flush()

    # Grant explicit building access if building IDs were provided
    if body.buildingIds:
        for bid in body.buildingIds:
            b = await db.execute(select(Building).where(Building.id == bid))
            if b.scalar_one_or_none() is None:
                continue  # skip invalid building IDs
            access = UserBuildingAccess(
                user_id=new_user.id,
                building_id=bid,
            )
            db.add(access)
        await db.flush()

    return OccupantOnboardResponse(
        status="onboarded",
        userId=new_user.id,
        tenantId=tenant_id,
    )


# ── BuildingTenant mappings ──────────────────────────────────────────────


@router.get("/building-tenants", response_model=list[BuildingTenantResponse])
async def list_building_tenants(
    buildingId: str | None = Query(None, description="Filter by building"),
    tenantId: str | None = Query(None, description="Filter by tenant"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List building-tenant mappings, optionally filtered.

    - Admins & building FMs see all.
    - Tenant FMs & occupants only see mappings for their own tenant.
    """
    stmt = select(BuildingTenant)
    if buildingId:
        stmt = stmt.where(BuildingTenant.building_id == buildingId)
    if tenantId:
        stmt = stmt.where(BuildingTenant.tenant_id == tenantId)

    # Tenant isolation for non-admin / non-building-FM users
    if user.role not in (UserRole.admin, UserRole.building_facility_manager):
        if user.tenant_id:
            stmt = stmt.where(BuildingTenant.tenant_id == user.tenant_id)
        else:
            # Independent user has no tenant mappings to see
            return []

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        BuildingTenantResponse(
            id=r.id,
            buildingId=r.building_id,
            tenantId=r.tenant_id,
            tenantName=r.tenant.name if r.tenant else None,
            floors=r.floors,
            zones=r.zones,
            isActive=r.is_active,
        )
        for r in rows
    ]


@router.post("/building-tenants", response_model=BuildingTenantResponse, status_code=201)
async def assign_tenant_to_building(
    body: BuildingTenantCreateRequest,
    user: User = Depends(require_role("admin", "building_facility_manager")),
    db: AsyncSession = Depends(get_db),
):
    """Assign a tenant to a building with floor/zone location info."""
    # Verify building exists
    b = await db.execute(select(Building).where(Building.id == body.buildingId))
    if b.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Building not found")

    # Verify tenant exists
    t_result = await db.execute(select(Tenant).where(Tenant.id == body.tenantId))
    t = t_result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    bt = BuildingTenant(
        building_id=body.buildingId,
        tenant_id=body.tenantId,
        floors=body.floors,
        zones=body.zones,
    )
    db.add(bt)
    await db.flush()
    return BuildingTenantResponse(
        id=bt.id,
        buildingId=bt.building_id,
        tenantId=bt.tenant_id,
        tenantName=t.name,
        floors=bt.floors,
        zones=bt.zones,
        isActive=bt.is_active,
    )


@router.get("/building-tenants/{bt_id}", response_model=BuildingTenantResponse)
async def get_building_tenant(
    bt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single building-tenant mapping."""
    result = await db.execute(
        select(BuildingTenant).where(BuildingTenant.id == bt_id)
    )
    bt = result.scalar_one_or_none()
    if bt is None:
        raise HTTPException(status_code=404, detail="BuildingTenant not found")

    # Tenant isolation
    if user.role not in (UserRole.admin, UserRole.building_facility_manager):
        if bt.tenant_id != user.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant isolation violation")

    return BuildingTenantResponse(
        id=bt.id,
        buildingId=bt.building_id,
        tenantId=bt.tenant_id,
        tenantName=bt.tenant.name if bt.tenant else None,
        floors=bt.floors,
        zones=bt.zones,
        isActive=bt.is_active,
    )


# ── User Building Access (explicit grants) ──────────────────────────────


@router.get("/user-building-access", response_model=list[UserBuildingAccessResponse])
async def list_user_building_access(
    userId: str | None = Query(None, description="Filter by user"),
    buildingId: str | None = Query(None, description="Filter by building"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List explicit building access grants.

    - Admins & building FMs see all.
    - Others only see their own grants.
    """
    stmt = select(UserBuildingAccess).where(
        UserBuildingAccess.is_active == True  # noqa: E712
    )
    if userId:
        stmt = stmt.where(UserBuildingAccess.user_id == userId)
    if buildingId:
        stmt = stmt.where(UserBuildingAccess.building_id == buildingId)

    # Non-admin / non-building-FM users can only see their own grants
    if user.role not in (UserRole.admin, UserRole.building_facility_manager):
        stmt = stmt.where(UserBuildingAccess.user_id == user.id)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        UserBuildingAccessResponse(
            id=r.id,
            userId=r.user_id,
            buildingId=r.building_id,
            grantedBy=r.granted_by,
            isActive=r.is_active,
            createdAt=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]


@router.post(
    "/user-building-access",
    response_model=UserBuildingAccessResponse,
    status_code=201,
)
async def grant_building_access(
    body: UserBuildingAccessGrantRequest,
    user: User = Depends(require_role("admin", "building_facility_manager",
                                      "tenant_facility_manager")),
    db: AsyncSession = Depends(get_db),
):
    """Grant a user access to a building (FM / admin only).

    - **Admin & building FM** can grant access to any user for any building.
    - **Tenant FM** can only grant access to users within their own tenant and
      for buildings their tenant is mapped to.
    """
    # Verify target user exists
    target = await db.execute(select(User).where(User.id == body.userId))
    target_user = target.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="Target user not found")

    # Verify building exists
    b = await db.execute(select(Building).where(Building.id == body.buildingId))
    if b.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Building not found")

    # Tenant FM extra checks
    if user.role == UserRole.tenant_facility_manager:
        if target_user.tenant_id != user.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Tenant FMs can only grant access to their own tenant's users",
            )
        bt_check = await db.execute(
            select(BuildingTenant).where(
                BuildingTenant.building_id == body.buildingId,
                BuildingTenant.tenant_id == user.tenant_id,
                BuildingTenant.is_active == True,  # noqa: E712
            )
        )
        if bt_check.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=403,
                detail="Tenant FMs can only grant access to buildings their tenant occupies",
            )

    # Check for existing active grant (idempotent)
    existing = await db.execute(
        select(UserBuildingAccess).where(
            UserBuildingAccess.user_id == body.userId,
            UserBuildingAccess.building_id == body.buildingId,
            UserBuildingAccess.is_active == True,  # noqa: E712
        )
    )
    if (row := existing.scalar_one_or_none()) is not None:
        return UserBuildingAccessResponse(
            id=row.id,
            userId=row.user_id,
            buildingId=row.building_id,
            grantedBy=row.granted_by,
            isActive=row.is_active,
            createdAt=row.created_at.isoformat() if row.created_at else None,
        )

    access = UserBuildingAccess(
        user_id=body.userId,
        building_id=body.buildingId,
        granted_by=user.id,
    )
    db.add(access)
    await db.flush()

    return UserBuildingAccessResponse(
        id=access.id,
        userId=access.user_id,
        buildingId=access.building_id,
        grantedBy=access.granted_by,
        isActive=access.is_active,
        createdAt=access.created_at.isoformat() if access.created_at else None,
    )


@router.delete("/user-building-access/{access_id}", status_code=204)
async def revoke_building_access(
    access_id: str,
    user: User = Depends(require_role("admin", "building_facility_manager",
                                      "tenant_facility_manager")),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a user's explicit building access grant (soft-delete)."""
    result = await db.execute(
        select(UserBuildingAccess).where(UserBuildingAccess.id == access_id)
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        raise HTTPException(status_code=404, detail="Access grant not found")

    # Tenant FM can only revoke grants for their own tenant's users
    if user.role == UserRole.tenant_facility_manager:
        target = await db.execute(select(User).where(User.id == grant.user_id))
        target_user = target.scalar_one_or_none()
        if target_user and target_user.tenant_id != user.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Tenant FMs can only revoke access for their own tenant's users",
            )

    grant.is_active = False
    await db.flush()
