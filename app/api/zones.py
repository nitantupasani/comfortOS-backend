"""Zone CRUD API.

    GET    /zones/{building_id}            -> List zones for a building
    POST   /zones                           -> Create a zone
    PUT    /zones/{zone_id}                 -> Update zone
    DELETE /zones/{zone_id}                 -> Delete zone
    POST   /zones/{zone_id}/members         -> Add members
    DELETE /zones/{zone_id}/members/{loc_id} -> Remove a member
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.zone import Zone, ZoneMember
from ..schemas.zone import ZoneCreate, ZoneUpdate, ZoneMemberAdd

router = APIRouter(prefix="/zones", tags=["zones"])

_ADMIN_FM = (UserRole.admin, UserRole.building_facility_manager, UserRole.tenant_facility_manager)


@router.get("/{building_id}")
async def list_zones(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all zones for a building with their members."""
    result = await db.execute(
        select(Zone)
        .where(Zone.building_id == building_id)
        .order_by(Zone.name)
    )
    return [z.to_api_dict() for z in result.scalars().all()]


@router.post("", status_code=201)
async def create_zone(
    body: ZoneCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a zone and optionally add initial members."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    zone = Zone(
        building_id=body.buildingId,
        name=body.name,
        zone_type=body.zoneType,
        external_refs=body.externalRefs,
        metadata_=body.metadata,
    )
    db.add(zone)
    await db.flush()

    if body.memberLocationIds:
        for loc_id in body.memberLocationIds:
            db.add(ZoneMember(zone_id=zone.id, location_id=loc_id))
        await db.flush()

    await db.refresh(zone)
    return zone.to_api_dict()


@router.put("/{zone_id}")
async def update_zone(
    zone_id: str,
    body: ZoneUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update zone properties."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    zone = await db.get(Zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    for field, attr in [
        ("name", "name"), ("zoneType", "zone_type"),
        ("externalRefs", "external_refs"), ("metadata", "metadata_"),
    ]:
        val = getattr(body, field)
        if val is not None:
            setattr(zone, attr, val)

    await db.flush()
    await db.refresh(zone)
    return zone.to_api_dict()


@router.delete("/{zone_id}", status_code=204)
async def delete_zone(
    zone_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    zone = await db.get(Zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    await db.execute(delete(ZoneMember).where(ZoneMember.zone_id == zone_id))
    await db.delete(zone)


@router.post("/{zone_id}/members", status_code=201)
async def add_zone_members(
    zone_id: str,
    body: ZoneMemberAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add locations to a zone."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    zone = await db.get(Zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    for loc_id in body.locationIds:
        db.add(ZoneMember(zone_id=zone_id, location_id=loc_id))
    await db.flush()

    await db.refresh(zone)
    return zone.to_api_dict()


@router.delete("/{zone_id}/members/{location_id}", status_code=204)
async def remove_zone_member(
    zone_id: str,
    location_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    await db.execute(
        delete(ZoneMember)
        .where(ZoneMember.zone_id == zone_id, ZoneMember.location_id == location_id)
    )
