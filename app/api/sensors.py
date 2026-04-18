"""Sensor registry CRUD API.

    GET    /sensors/{building_id}         -> List sensors for a building
    POST   /sensors                        -> Register a sensor
    PUT    /sensors/{sensor_id}            -> Update sensor config
    DELETE /sensors/{sensor_id}            -> Remove a sensor
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.sensor import Sensor
from ..models.location import Location
from ..schemas.sensor import SensorCreate, SensorUpdate

router = APIRouter(prefix="/sensors", tags=["sensors"])

_ADMIN_FM = (UserRole.admin, UserRole.building_facility_manager, UserRole.tenant_facility_manager)


@router.get("/{building_id}")
async def list_sensors(
    building_id: str,
    roomId: str | None = Query(None, description="Filter by room"),
    metricType: str | None = Query(None, description="Filter by metric type"),
    activeOnly: bool = Query(True, description="Only active sensors"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List sensors for a building with optional filters."""
    stmt = select(Sensor).where(Sensor.building_id == building_id)
    if roomId:
        stmt = stmt.where(Sensor.room_id == roomId)
    if activeOnly:
        stmt = stmt.where(Sensor.is_active == True)  # noqa: E712
    result = await db.execute(stmt.order_by(Sensor.room_id, Sensor.priority))
    sensors = result.scalars().all()

    if metricType:
        sensors = [s for s in sensors if metricType in (s.metric_types or [])]

    return [s.to_api_dict() for s in sensors]


@router.post("", status_code=201)
async def create_sensor(
    body: SensorCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new sensor."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    # Validate room exists and is type=room
    room = await db.get(Location, body.roomId)
    if not room or room.type != "room":
        raise HTTPException(status_code=422, detail="roomId must reference a location of type 'room'")
    if room.building_id != body.buildingId:
        raise HTTPException(status_code=422, detail="Room must be in the specified building")

    # Validate placement if provided
    if body.placementId:
        placement = await db.get(Location, body.placementId)
        if not placement or placement.type != "placement":
            raise HTTPException(status_code=422, detail="placementId must reference a location of type 'placement'")
        if placement.parent_id != body.roomId:
            raise HTTPException(status_code=422, detail="Placement must be a child of the specified room")

    sensor = Sensor(
        building_id=body.buildingId,
        room_id=body.roomId,
        placement_id=body.placementId,
        zone_id=body.zoneId,
        sensor_type=body.sensorType,
        metric_types=body.metricTypes,
        source_endpoint_id=body.sourceEndpointId,
        source_identifier=body.sourceIdentifier,
        unit_map=body.unitMap,
        priority=body.priority,
        is_preferred=body.isPreferred,
        aggregation_group=body.aggregationGroup,
        calibration_offset=body.calibrationOffset,
        metadata_=body.metadata,
    )
    db.add(sensor)
    await db.flush()
    await db.refresh(sensor)
    return sensor.to_api_dict()


@router.put("/{sensor_id}")
async def update_sensor(
    sensor_id: str,
    body: SensorUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update sensor configuration."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    sensor = await db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    field_map = {
        "roomId": "room_id",
        "placementId": "placement_id",
        "zoneId": "zone_id",
        "sensorType": "sensor_type",
        "metricTypes": "metric_types",
        "sourceEndpointId": "source_endpoint_id",
        "sourceIdentifier": "source_identifier",
        "unitMap": "unit_map",
        "priority": "priority",
        "isPreferred": "is_preferred",
        "aggregationGroup": "aggregation_group",
        "isActive": "is_active",
        "calibrationOffset": "calibration_offset",
        "metadata": "metadata_",
    }
    for schema_field, model_field in field_map.items():
        val = getattr(body, schema_field)
        if val is not None:
            setattr(sensor, model_field, val)

    await db.flush()
    await db.refresh(sensor)
    return sensor.to_api_dict()


@router.delete("/{sensor_id}", status_code=204)
async def delete_sensor(
    sensor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a sensor from the registry."""
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    sensor = await db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    await db.delete(sensor)
