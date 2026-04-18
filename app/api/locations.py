"""Location hierarchy CRUD API.

    GET    /locations/{building_id}         -> List locations for a building
    GET    /locations/{building_id}/tree    -> Full hierarchy tree
    POST   /locations                       -> Create a location
    POST   /locations/batch                 -> Create multiple locations
    PUT    /locations/{location_id}         -> Update a location
    DELETE /locations/{location_id}         -> Delete a location
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.location import Location
from ..schemas.location import (
    LocationCreate,
    LocationUpdate,
    LocationBatchCreate,
    LocationTreeNode,
)

router = APIRouter(prefix="/locations", tags=["locations"])

_ADMIN_FM = (UserRole.admin, UserRole.building_facility_manager, UserRole.tenant_facility_manager)


@router.get("/{building_id}")
async def list_locations(
    building_id: str,
    type: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all locations for a building, optionally filtered by type."""
    stmt = (
        select(Location)
        .where(Location.building_id == building_id)
        .order_by(Location.sort_order, Location.name)
    )
    if type:
        stmt = stmt.where(Location.type == type)
    result = await db.execute(stmt)
    return [loc.to_api_dict() for loc in result.scalars().all()]


@router.get("/{building_id}/tree")
async def get_location_tree(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full location hierarchy as a nested tree."""
    result = await db.execute(
        select(Location)
        .where(Location.building_id == building_id)
        .order_by(Location.sort_order, Location.name)
    )
    all_locs = result.scalars().all()

    # Build tree
    by_id = {loc.id: loc for loc in all_locs}
    children_map: dict[str | None, list[Location]] = {}
    for loc in all_locs:
        children_map.setdefault(loc.parent_id, []).append(loc)

    def _build_node(loc: Location) -> dict:
        node = loc.to_api_dict()
        node["children"] = [
            _build_node(c) for c in children_map.get(loc.id, [])
        ]
        return node

    roots = children_map.get(None, [])
    return [_build_node(r) for r in roots]


@router.post("", status_code=201)
async def create_location(
    body: LocationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a single location node."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    if body.type not in Location.VALID_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid type. Must be one of: {', '.join(sorted(Location.VALID_TYPES))}",
        )

    # Validate parent hierarchy
    if body.parentId:
        parent = await db.get(Location, body.parentId)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent location not found")
        if parent.building_id != body.buildingId:
            raise HTTPException(status_code=422, detail="Parent must be in the same building")
        parent_level = Location.TYPE_LEVEL.get(parent.type, 0)
        child_level = Location.TYPE_LEVEL.get(body.type, 0)
        if child_level <= parent_level:
            raise HTTPException(
                status_code=422,
                detail=f"Child type '{body.type}' (level {child_level}) must be below parent type '{parent.type}' (level {parent_level})",
            )
    elif body.type != "building":
        raise HTTPException(status_code=422, detail="Only building type can have no parent")

    loc = Location(
        building_id=body.buildingId,
        parent_id=body.parentId,
        type=body.type,
        name=body.name,
        code=body.code,
        sort_order=body.sortOrder,
        orientation=body.orientation,
        usage_type=body.usageType,
        external_refs=body.externalRefs,
        metadata_=body.metadata,
    )
    db.add(loc)
    await db.flush()
    await db.refresh(loc)
    return loc.to_api_dict()


@router.post("/batch", status_code=201)
async def create_locations_batch(
    body: LocationBatchCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple location nodes in one request (initial building setup)."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    created = []
    for loc_in in body.locations:
        if loc_in.type not in Location.VALID_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid type: {loc_in.type}")
        loc = Location(
            building_id=body.buildingId,
            parent_id=loc_in.parentId,
            type=loc_in.type,
            name=loc_in.name,
            code=loc_in.code,
            sort_order=loc_in.sortOrder,
            orientation=loc_in.orientation,
            usage_type=loc_in.usageType,
            external_refs=loc_in.externalRefs,
            metadata_=loc_in.metadata,
        )
        db.add(loc)
        created.append(loc)

    await db.flush()
    for loc in created:
        await db.refresh(loc)
    return [loc.to_api_dict() for loc in created]


@router.put("/{location_id}")
async def update_location(
    location_id: str,
    body: LocationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a location node."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    loc = await db.get(Location, location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")

    for field, attr in [
        ("name", "name"), ("code", "code"), ("sortOrder", "sort_order"),
        ("orientation", "orientation"), ("usageType", "usage_type"),
        ("externalRefs", "external_refs"), ("metadata", "metadata_"),
    ]:
        val = getattr(body, field)
        if val is not None:
            setattr(loc, attr, val)

    await db.flush()
    await db.refresh(loc)
    return loc.to_api_dict()


@router.delete("/{location_id}", status_code=204)
async def delete_location(
    location_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a location node (fails if it has children)."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    loc = await db.get(Location, location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")

    # Check for children
    result = await db.execute(
        select(Location.id).where(Location.parent_id == location_id).limit(1)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Cannot delete location with children")

    await db.delete(loc)
