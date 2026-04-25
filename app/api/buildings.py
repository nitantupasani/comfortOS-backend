"""
Building & Config API routes.

    GET    /buildings                     → List buildings (open + tenant-mapped)
    POST   /buildings                     → Create building (admin only)
    PUT    /buildings/{id}                → Update building (admin only)
    GET    /buildings/{id}/dashboard      → SDUI dashboard config
    GET    /buildings/{id}/vote-form      → SDUI vote form schema
    GET    /buildings/{id}/location-form  → Floor/room hierarchy
    GET    /buildings/{id}/config         → Full app config
    PUT    /buildings/{id}/config         → Upsert SDUI config (admin + FM)
    GET    /buildings/{id}/comfort        → Aggregate comfort data
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
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


# ── Request schemas ───────────────────────────────────────────────────────────

class BuildingCreate(BaseModel):
    name: str
    address: str
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    requiresAccessPermission: bool = False


class BuildingUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    requiresAccessPermission: bool | None = None


class BuildingConfigUpdate(BaseModel):
    dashboardLayout: Any | None = None
    voteFormSchema: Any | None = None
    locationFormConfig: Any | None = None


class PersonalBlockSpec(BaseModel):
    """A user-defined block / wing inside a personal building.

    Each block covers a contiguous range of floors. Floors can be
    negative (basements) so we don't impose a >= 0 constraint.
    """
    name: str
    startFloor: int
    endFloor: int


class PersonalBuildingCreate(BaseModel):
    name: str
    city: str | None = None
    blocks: list[PersonalBlockSpec] | None = None
    # Legacy fields retained so older clients on cached bundles still
    # succeed; preferred new shape is `blocks`.
    floorCount: int | None = None
    zoneCount: int | None = None
    floor: str | None = None
    zone: str | None = None


class PersonalRoomAdd(BaseModel):
    """Body for adding a room to a personal building.

    The structured fields (block / floor / label) are preferred. The
    free-form `room` field is accepted for older clients and gets
    stored as a label-only entry."""
    block: str | None = None
    floor: int | None = None
    label: str | None = None
    room: str | None = None


class PersonalRoomRemove(BaseModel):
    """Match by structured fields when present, else by legacy label."""
    block: str | None = None
    floor: int | None = None
    label: str | None = None
    room: str | None = None


_MAX_PERSONAL_BLOCKS = 10
_MAX_PERSONAL_ROOMS = 50


PERSONAL_BUILDING_LIMIT = 3

# Default vote form seeded for personal buildings. Uses the canonical
# -3..+3 thermal scale so the web VoteFormRenderer (clamped to ±3)
# shows all 7 options; Flutter renders any min..max range, so it works
# there too.
_DEFAULT_PERSONAL_VOTE_FORM: dict = {
    "schemaVersion": 2,
    "formTitle": "Comfort Vote",
    "formDescription": "Quick survey about your environment – takes under a minute.",
    "thanksMessage": "Thanks for your feedback!",
    "allowAnonymous": False,
    "cooldownMinutes": 30,
    "fields": [
        {
            "key": "thermal_comfort",
            "type": "thermal_scale",
            "question": "How hot or cold do you feel?",
            "min": -3,
            "max": 3,
            "defaultValue": 0,
            "labels": {
                "-3": "Cold",
                "-2": "Cool",
                "-1": "Slightly Cool",
                "0": "Neutral",
                "1": "Slightly Warm",
                "2": "Warm",
                "3": "Hot",
            },
        },
        {
            "key": "thermal_preference",
            "type": "single_select",
            "question": "Do you want to be warmer or cooler?",
            "options": [
                {"label": "Warmer", "value": 1, "color": "orange", "emoji": "🔥"},
                {"label": "I am good", "value": 2, "color": "green", "emoji": "👍"},
                {"label": "Cooler", "value": 3, "color": "blue", "emoji": "❄️"},
            ],
        },
        {
            "key": "air_quality",
            "type": "multi_select",
            "question": "What do you think about the air quality?",
            "options": [
                {"label": "Suffocating", "value": "suffocating", "emoji": "😤"},
                {"label": "Humid", "value": "humid", "emoji": "💧"},
                {"label": "Dry", "value": "dry", "emoji": "🏜️"},
                {"label": "Smelly", "value": "smelly", "emoji": "🤢"},
                {
                    "label": "All good!",
                    "value": "all_good",
                    "exclusive": True,
                    "color": "green",
                    "emoji": "✅",
                },
            ],
        },
    ],
}


router = APIRouter(prefix="/buildings", tags=["buildings"])


def _thermal_comfort_to_score(value: int | float) -> float | None:
    """Convert a thermal comfort vote to a 1–10 satisfaction score.

    Scale: -3 (cold) → 0 (neutral/perfect) → +3 (hot).
    Satisfaction is highest (10) at neutral (0) and lowest (1) at extremes (±3).
    Legacy 1–7 values are first centred to -3..+3  (subtract 4).
    """
    if 1 <= value <= 7:
        value = value - 4  # centre: 1→-3, 4→0, 7→+3
    if -3 <= value <= 3:
        return round(1 + 9 * (1 - abs(value) / 3), 1)
    return None


@router.get("")
async def list_buildings(
    tenantId: str | None = Query(None, description="Optional tenant filter"),
    managedOnly: bool = Query(False, description="When true, only return buildings the caller manages (tenant-mapped or explicitly granted). Used by FM pages."),
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

    When ``managedOnly`` is true (for FM management pages), only buildings
    the user has a management relationship with are returned — open buildings
    not mapped to the user's tenant are excluded.
    """

    # When managedOnly is set, return only buildings the FM actually manages
    if managedOnly:
        if user.role == UserRole.admin:
            # Admin manages all buildings
            result = await db.execute(select(Building))
            return [b.to_api_dict() for b in result.scalars().all()]

        # building_facility_manager / tenant_facility_manager / occupant:
        # only tenant-mapped + explicitly granted
        accessible_ids: list[str] = []
        if user.tenant_id:
            bt_result = await db.execute(
                select(BuildingTenant.building_id).where(
                    BuildingTenant.tenant_id == user.tenant_id,
                    BuildingTenant.is_active == True,  # noqa: E712
                )
            )
            accessible_ids.extend(r[0] for r in bt_result.all())

        uba_result = await db.execute(
            select(UserBuildingAccess.building_id).where(
                UserBuildingAccess.user_id == user.id,
                UserBuildingAccess.is_active == True,  # noqa: E712
            )
        )
        accessible_ids.extend(r[0] for r in uba_result.all())

        if not accessible_ids:
            return []

        unique_ids = list(set(accessible_ids))
        result = await db.execute(
            select(Building).where(Building.id.in_(unique_ids))
        )
        return [b.to_api_dict() for b in result.scalars().all()]

    # --- 1. Open buildings (everyone can see) ---
    open_stmt = select(Building).where(
        Building.requires_access_permission == False  # noqa: E712
    )

    # --- 2. Restricted buildings the user may access ---
    if user.role == UserRole.admin:
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
        if user.role != UserRole.admin:
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


@router.post("", status_code=201)
async def create_building(
    body: BuildingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new building. Admin only."""
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")

    building = Building(
        name=body.name,
        address=body.address,
        city=body.city,
        latitude=body.latitude,
        longitude=body.longitude,
        requires_access_permission=body.requiresAccessPermission,
    )
    db.add(building)
    await db.commit()
    await db.refresh(building)
    return building.to_api_dict()


async def _list_personal_buildings_for_user(
    user_id: str, db: AsyncSession
) -> list[Building]:
    """Return Buildings the user self-registered (isPersonal flag in metadata)."""
    result = await db.execute(
        select(Building)
        .join(UserBuildingAccess, UserBuildingAccess.building_id == Building.id)
        .where(
            UserBuildingAccess.user_id == user_id,
            UserBuildingAccess.is_active == True,  # noqa: E712
        )
    )
    buildings = result.scalars().all()
    return [
        b for b in buildings
        if isinstance(b.metadata_, dict)
        and b.metadata_.get("isPersonal") is True
        and b.metadata_.get("createdByUserId") == user_id
    ]


@router.get("/personal")
async def list_personal_buildings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the buildings this occupant self-registered."""
    buildings = await _list_personal_buildings_for_user(user.id, db)
    return [b.to_api_dict() for b in buildings]


@router.post("/personal", status_code=201)
async def create_personal_building(
    body: PersonalBuildingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Occupant self-registers a building (max 3 per user).

    Stores `{isPersonal, createdByUserId, floorCount, zoneCount,
    rooms}` in `metadata_` (with legacy `floor` / `zone` kept for old
    clients), grants the user access via `UserBuildingAccess`, and
    seeds a `BuildingConfig` with the default comfort vote form.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    existing = await _list_personal_buildings_for_user(user.id, db)
    if len(existing) >= PERSONAL_BUILDING_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"You can add up to {PERSONAL_BUILDING_LIMIT} personal buildings",
        )

    legacy_floor = (body.floor or "").strip() or None
    legacy_zone = (body.zone or "").strip() or None
    city = (body.city or "").strip() or None

    blocks: list[dict] = []
    if body.blocks:
        if len(body.blocks) > _MAX_PERSONAL_BLOCKS:
            raise HTTPException(
                status_code=400,
                detail=f"Up to {_MAX_PERSONAL_BLOCKS} blocks per building",
            )
        for b in body.blocks:
            block_name = b.name.strip()
            if not block_name:
                raise HTTPException(status_code=400, detail="Block name is required")
            if b.endFloor < b.startFloor:
                raise HTTPException(
                    status_code=400,
                    detail=f"Block '{block_name}': end floor must be ≥ start floor",
                )
            blocks.append({
                "name": block_name,
                "startFloor": b.startFloor,
                "endFloor": b.endFloor,
            })

    metadata: dict = {
        "isPersonal": True,
        "createdByUserId": user.id,
        "blocks": blocks,
        "rooms": [],
    }
    # Legacy keys kept on the row only so older clients can still read
    # something sensible from existing fields. New clients should ignore
    # them in favor of `blocks`.
    if body.floorCount is not None and body.floorCount >= 0:
        metadata["floorCount"] = body.floorCount
    if body.zoneCount is not None and body.zoneCount >= 0:
        metadata["zoneCount"] = body.zoneCount
    if legacy_floor:
        metadata["floor"] = legacy_floor
    if legacy_zone:
        metadata["zone"] = legacy_zone

    building = Building(
        name=name,
        address=name,
        city=city,
        requires_access_permission=True,
        metadata_=metadata,
    )
    db.add(building)
    await db.flush()

    db.add(UserBuildingAccess(
        user_id=user.id,
        building_id=building.id,
        granted_by=user.id,
        is_active=True,
    ))

    db.add(BuildingConfig(
        building_id=building.id,
        vote_form_schema=_DEFAULT_PERSONAL_VOTE_FORM,
        is_active=True,
    ))

    await db.commit()
    await db.refresh(building)
    return building.to_api_dict()


async def _load_owned_personal_building(
    building_id: str, user: User, db: AsyncSession
) -> Building:
    """Load a building and verify the caller is its personal-building owner."""
    result = await db.execute(select(Building).where(Building.id == building_id))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")
    meta = building.metadata_ if isinstance(building.metadata_, dict) else {}
    if not (meta.get("isPersonal") and meta.get("createdByUserId") == user.id):
        raise HTTPException(status_code=403, detail="Not your personal building")
    return building


def _normalize_room_entry(
    block: str | None,
    floor: int | None,
    label: str | None,
    legacy_room: str | None,
) -> dict:
    """Build the canonical {block, floor, label} dict.

    Older clients send `room` as a single string; we store that as a
    label-only entry so they keep working. Newer clients send the
    structured fields directly.
    """
    out: dict = {}
    if block and block.strip():
        out["block"] = block.strip()
    if floor is not None:
        out["floor"] = int(floor)
    if label and label.strip():
        out["label"] = label.strip()
    elif legacy_room and legacy_room.strip():
        out["label"] = legacy_room.strip()
    return out


def _rooms_match(a: dict, b: dict) -> bool:
    """Compare two room entries by their full identity (block/floor/label)."""
    return (
        a.get("block") == b.get("block")
        and a.get("floor") == b.get("floor")
        and a.get("label") == b.get("label")
    )


@router.post("/personal/{building_id}/rooms", status_code=200)
async def add_personal_room(
    building_id: str,
    body: PersonalRoomAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a room to a personal building. Idempotent; max 50 rooms.

    Accepts either the structured `{block, floor, label}` shape or a
    legacy free-form `room` string for backward compat.
    """
    building = await _load_owned_personal_building(building_id, user, db)

    new_room = _normalize_room_entry(body.block, body.floor, body.label, body.room)
    if "label" not in new_room:
        raise HTTPException(status_code=400, detail="Room label is required")

    meta = dict(building.metadata_) if isinstance(building.metadata_, dict) else {}
    rooms_raw = list(meta.get("rooms") or [])

    # Normalize any legacy string rooms to dict form on the fly.
    rooms: list[dict] = []
    for r in rooms_raw:
        if isinstance(r, str):
            rooms.append({"label": r})
        elif isinstance(r, dict):
            rooms.append(r)

    if any(_rooms_match(r, new_room) for r in rooms):
        # Already present — return as-is.
        meta["rooms"] = rooms
    else:
        if len(rooms) >= _MAX_PERSONAL_ROOMS:
            raise HTTPException(
                status_code=400,
                detail=f"Maximum of {_MAX_PERSONAL_ROOMS} rooms per personal building",
            )
        rooms.append(new_room)
        meta["rooms"] = rooms

    building.metadata_ = meta
    await db.commit()
    await db.refresh(building)
    return building.to_api_dict()


@router.post("/personal/{building_id}/rooms/remove", status_code=200)
async def remove_personal_room(
    building_id: str,
    body: PersonalRoomRemove,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a room from a personal building (by structured fields or legacy label)."""
    building = await _load_owned_personal_building(building_id, user, db)

    target = _normalize_room_entry(body.block, body.floor, body.label, body.room)
    if not target:
        raise HTTPException(status_code=400, detail="Room to remove is required")

    meta = dict(building.metadata_) if isinstance(building.metadata_, dict) else {}
    rooms_raw = list(meta.get("rooms") or [])
    rooms: list[dict] = []
    for r in rooms_raw:
        if isinstance(r, str):
            entry = {"label": r}
        elif isinstance(r, dict):
            entry = r
        else:
            continue
        if not _rooms_match(entry, target):
            rooms.append(entry)

    meta["rooms"] = rooms
    building.metadata_ = meta
    await db.commit()
    await db.refresh(building)
    return building.to_api_dict()


# Tables with an FK to buildings.id that need to be cleaned up before
# the building row itself can be deleted. Order matters only insofar as
# any table referenced by another (e.g. chat_sessions → chat_messages
# via ON DELETE CASCADE) clears its dependents automatically.
_BUILDING_FK_TABLES: tuple[str, ...] = (
    "user_building_access",
    "building_configs",
    "building_tenants",
    "building_connectors",
    "building_telemetry_config",
    "presence_events",
    "beacons",
    "sensors",
    "telemetry_readings",
    "telemetry_endpoints",
    "votes",
    "complaints",
    "fm_role_requests",
    "chat_sessions",
    "zones",
    "locations",
)


@router.post("/personal/{building_id}/delete", status_code=204)
async def delete_personal_building(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a personal building the caller created.

    POST is used instead of DELETE because some hosting layers in front
    of the API are flaky with DELETE methods.

    Cascades the cleanup across every table that has an FK to
    ``buildings.id`` so a presence-event, chat session, vote, etc. tied
    to the personal building doesn't pin the row at commit time.
    """
    from sqlalchemy import text

    result = await db.execute(select(Building).where(Building.id == building_id))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    meta = building.metadata_ if isinstance(building.metadata_, dict) else {}
    if not (meta.get("isPersonal") and meta.get("createdByUserId") == user.id):
        raise HTTPException(status_code=403, detail="Not your personal building")

    for table in _BUILDING_FK_TABLES:
        # Each table name is a hard-coded literal from _BUILDING_FK_TABLES
        # (no user input), so the f-string interpolation is safe.
        await db.execute(
            text(f"DELETE FROM {table} WHERE building_id = :bid"),
            {"bid": building_id},
        )
    await db.delete(building)
    await db.commit()
    return Response(status_code=204)


@router.put("/{building_id}")
async def update_building(
    building_id: str,
    body: BuildingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update building fields. Admin only."""
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")

    result = await db.execute(select(Building).where(Building.id == building_id))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    if body.name is not None:
        building.name = body.name
    if body.address is not None:
        building.address = body.address
    if body.city is not None:
        building.city = body.city
    if body.latitude is not None:
        building.latitude = body.latitude
    if body.longitude is not None:
        building.longitude = body.longitude
    if body.requiresAccessPermission is not None:
        building.requires_access_permission = body.requiresAccessPermission

    await db.commit()
    await db.refresh(building)
    return building.to_api_dict()


async def _get_accessible_building(
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
    if user.role == UserRole.admin:
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
    await _get_accessible_building(building_id, user, db)
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
    await _get_accessible_building(building_id, user, db)
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
    await _get_accessible_building(building_id, user, db)
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
    building = await _get_accessible_building(building_id, user, db)
    config = await _get_active_config(building_id, db)

    return {
        "schemaVersion": config.schema_version if config else 1,
        "dashboardLayout": config.dashboard_layout if config else None,
        "voteFormSchema": config.vote_form_schema if config else None,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }


@router.put("/{building_id}/config")
async def update_building_config(
    building_id: str,
    body: BuildingConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert SDUI config for a building. Admin or Facility Manager only."""
    _FM_ROLES = (
        UserRole.admin,
        UserRole.building_facility_manager,
        UserRole.tenant_facility_manager,
    )
    if user.role not in _FM_ROLES:
        raise HTTPException(status_code=403, detail="Facility manager or admin only")

    # Verify building exists AND the caller has access
    await _get_accessible_building(building_id, user, db)

    config = await _get_active_config(building_id, db)
    if config is None:
        config = BuildingConfig(building_id=building_id)
        db.add(config)

    if body.dashboardLayout is not None:
        config.dashboard_layout = body.dashboardLayout
    if body.voteFormSchema is not None:
        config.vote_form_schema = body.voteFormSchema
    if body.locationFormConfig is not None:
        config.location_form_config = body.locationFormConfig
    config.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(config)
    return {
        "schemaVersion": config.schema_version,
        "dashboardLayout": config.dashboard_layout,
        "voteFormSchema": config.vote_form_schema,
        "locationFormConfig": config.location_form_config,
        "updatedAt": config.updated_at.isoformat(),
    }


@router.get("/{building_id}/comfort")
async def get_comfort_data(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate comfort data for a building. Returns 204 if no votes."""
    building = await _get_accessible_building(building_id, user, db)

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
                score = _thermal_comfort_to_score(thermal)
                if score is not None:
                    scores.append(score)

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
