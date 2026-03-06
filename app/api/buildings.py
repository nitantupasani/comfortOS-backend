"""
Building & Config API routes.

    GET  /buildings                     → List buildings (open + tenant-mapped)
    GET  /buildings/{id}/dashboard      → SDUI dashboard config
    GET  /buildings/{id}/vote-form      → SDUI vote form schema
    GET  /buildings/{id}/location-form  → Floor/room hierarchy
    GET  /buildings/{id}/config         → Full app config
    GET  /buildings/{id}/comfort        → Aggregate comfort data
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.building import Building
from ..models.building_tenant import BuildingTenant
from ..models.building_config import BuildingConfig
from ..models.user_building_access import UserBuildingAccess
from ..models.vote import Vote

router = APIRouter(prefix="/buildings", tags=["buildings"])


@router.get("")
async def list_buildings(
    tenantId: str | None = Query(None, description="Optional tenant filter"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List buildings the caller may access.

    Rules
    -----
    - **Open buildings** (`requires_access_permission=False`) are visible to
      every authenticated user.
    - **Restricted buildings** are visible only when the caller's tenant is
      mapped to them via ``building_tenants``, or the caller is
      admin / building FM.

    When ``tenantId`` is supplied the response is filtered to buildings that
    tenant occupies (still including open buildings).
    """
    # --- 1. Open buildings (everyone can see) ---
    open_stmt = select(Building).where(
        Building.requires_access_permission == False  # noqa: E712
    )

    # --- 2. Restricted buildings the user may access ---
    if user.role in (UserRole.admin, UserRole.building_facility_manager):
        restricted_stmt = select(Building).where(
            Building.requires_access_permission == True  # noqa: E712
        )
    else:
        # Buildings accessible via tenant mapping
        tenant_building_ids: list[str] = []
        if user.tenant_id:
            bt_result = await db.execute(
                select(BuildingTenant.building_id).where(
                    BuildingTenant.tenant_id == user.tenant_id,
                    BuildingTenant.is_active == True,  # noqa: E712
                )
            )
            tenant_building_ids = [r[0] for r in bt_result.all()]

        # Buildings accessible via explicit grants
        uba_result = await db.execute(
            select(UserBuildingAccess.building_id).where(
                UserBuildingAccess.user_id == user.id,
                UserBuildingAccess.is_active == True,  # noqa: E712
            )
        )
        grant_building_ids = [r[0] for r in uba_result.all()]

        accessible_ids = list(set(tenant_building_ids + grant_building_ids))
        if accessible_ids:
            restricted_stmt = select(Building).where(
                Building.requires_access_permission == True,  # noqa: E712
                Building.id.in_(accessible_ids),
            )
        else:
            restricted_stmt = None

    # Optional tenant filter narrows restricted buildings
    if tenantId:
        if user.role not in (UserRole.admin, UserRole.building_facility_manager):
            if user.tenant_id and user.tenant_id != tenantId:
                raise HTTPException(status_code=403, detail="Tenant isolation violation")
        restricted_stmt = (
            select(Building)
            .join(BuildingTenant, BuildingTenant.building_id == Building.id)
            .where(
                Building.requires_access_permission == True,  # noqa: E712
                BuildingTenant.tenant_id == tenantId,
                BuildingTenant.is_active == True,  # noqa: E712
            )
        )

    open_result = await db.execute(open_stmt)
    seen_ids: set[str] = set()
    buildings: list[dict] = []
    for b in open_result.scalars().all():
        if b.id not in seen_ids:
            seen_ids.add(b.id)
            buildings.append(b.to_api_dict(tenant_id=tenantId))

    if restricted_stmt is not None:
        restricted_result = await db.execute(restricted_stmt)
        for b in restricted_result.scalars().all():
            if b.id not in seen_ids:
                seen_ids.add(b.id)
                buildings.append(b.to_api_dict(tenant_id=tenantId))

    return buildings


async def _get_building_with_access_check(
    building_id: str, user: User, db: AsyncSession
) -> Building:
    """Helper: load building and verify the user has access.

    - **Open buildings**: any authenticated user is allowed.
    - **Restricted buildings**:
        - Admin & building FM: always allowed.
        - Others: allowed only if their tenant is mapped via ``building_tenants``.
    """
    result = await db.execute(select(Building).where(Building.id == building_id))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    # Open building → everyone in
    if not building.requires_access_permission:
        return building

    # Restricted building → check roles / tenant mapping / explicit grants
    if user.role in (UserRole.admin, UserRole.building_facility_manager):
        return building

    # Check tenant-based access
    if user.tenant_id:
        bt_check = await db.execute(
            select(BuildingTenant).where(
                BuildingTenant.building_id == building_id,
                BuildingTenant.tenant_id == user.tenant_id,
                BuildingTenant.is_active == True,  # noqa: E712
            )
        )
        if bt_check.scalar_one_or_none() is not None:
            return building

    # Check explicit access grant
    uba_check = await db.execute(
        select(UserBuildingAccess).where(
            UserBuildingAccess.user_id == user.id,
            UserBuildingAccess.building_id == building_id,
            UserBuildingAccess.is_active == True,  # noqa: E712
        )
    )
    if uba_check.scalar_one_or_none() is not None:
        return building

    raise HTTPException(
        status_code=403,
        detail="This building requires access permission",
    )


async def _get_active_config(
    building_id: str, db: AsyncSession
) -> BuildingConfig | None:
    """Load the latest active config for a building."""
    result = await db.execute(
        select(BuildingConfig)
        .where(
            BuildingConfig.building_id == building_id,
            BuildingConfig.is_active == True,
        )
        .order_by(BuildingConfig.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/{building_id}/dashboard")
async def get_dashboard_config(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SDUI dashboard layout JSON. Returns 204 if no config exists."""
    await _get_building_with_access_check(building_id, user, db)
    config = await _get_active_config(building_id, db)
    if config is None or config.dashboard_layout is None:
        return Response(status_code=204)
    return config.dashboard_layout


@router.get("/{building_id}/vote-form")
async def get_vote_form_config(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SDUI vote form schema JSON. Returns 204 if no config exists."""
    await _get_building_with_access_check(building_id, user, db)
    config = await _get_active_config(building_id, db)
    if config is None or config.vote_form_schema is None:
        return Response(status_code=204)
    return config.vote_form_schema


@router.get("/{building_id}/location-form")
async def get_location_form_config(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SDUI location form config (floor/room hierarchy). Returns 204 if none."""
    await _get_building_with_access_check(building_id, user, db)
    config = await _get_active_config(building_id, db)
    if config is None or config.location_form_config is None:
        return Response(status_code=204)
    return config.location_form_config


@router.get("/{building_id}/config")
async def get_app_config(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full app config (schema version + all SDUI layouts)."""
    building = await _get_building_with_access_check(building_id, user, db)
    config = await _get_active_config(building_id, db)

    return {
        "schemaVersion": config.schema_version if config else 1,
        "dashboardLayout": config.dashboard_layout if config else None,
        "voteFormSchema": config.vote_form_schema if config else None,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{building_id}/comfort")
async def get_comfort_data(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate comfort data for a building. Returns 204 if no votes."""
    building = await _get_building_with_access_check(building_id, user, db)

    # Count votes and compute average comfort score
    result = await db.execute(
        select(
            func.count(Vote.vote_uuid).label("total"),
        ).where(Vote.building_id == building_id)
    )
    row = result.one()
    total_votes = row.total

    if total_votes == 0:
        return Response(status_code=204)

    # Compute a simple overall score from vote payloads.
    # In production this would be a more sophisticated aggregation.
    votes_result = await db.execute(
        select(Vote).where(Vote.building_id == building_id).limit(500)
    )
    votes = votes_result.scalars().all()

    scores = []
    for v in votes:
        # Extract thermal_comfort if present in payload
        if isinstance(v.payload, dict):
            thermal = v.payload.get("thermal_comfort")
            if thermal is not None and isinstance(thermal, (int, float)):
                # Map ASHRAE 7-point (-3 to +3) to 0-10 scale
                scores.append(((thermal + 3) / 6) * 10)

    overall = sum(scores) / len(scores) if scores else 5.0

    return {
        "buildingId": building_id,
        "buildingName": building.name,
        "overallScore": round(overall, 1),
        "totalVotes": total_votes,
        "computedAt": datetime.now(timezone.utc).isoformat(),
        "locations": [],
        "sduiConfig": None,
    }
