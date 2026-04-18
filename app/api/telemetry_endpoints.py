"""Telemetry Endpoint registry CRUD API.

    GET    /telemetry-endpoints/{building_id}           -> List endpoints
    POST   /telemetry-endpoints                          -> Register endpoint
    PUT    /telemetry-endpoints/{endpoint_id}             -> Update endpoint
    DELETE /telemetry-endpoints/{endpoint_id}             -> Remove endpoint
    POST   /telemetry-endpoints/{endpoint_id}/test       -> Test connection
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.telemetry_endpoint import TelemetryEndpoint
from ..schemas.telemetry_endpoint import EndpointCreate, EndpointUpdate

router = APIRouter(prefix="/telemetry-endpoints", tags=["telemetry-endpoints"])

_ADMIN_FM = (UserRole.admin, UserRole.building_facility_manager, UserRole.tenant_facility_manager)


@router.get("/{building_id}")
async def list_endpoints(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    result = await db.execute(
        select(TelemetryEndpoint)
        .where(TelemetryEndpoint.building_id == building_id)
        .order_by(TelemetryEndpoint.priority, TelemetryEndpoint.created_at)
    )
    return [ep.to_api_dict() for ep in result.scalars().all()]


@router.post("", status_code=201)
async def create_endpoint(
    body: EndpointCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    if body.endpointMode not in TelemetryEndpoint.VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid endpointMode. Must be one of: {', '.join(sorted(TelemetryEndpoint.VALID_MODES))}",
        )

    ep = TelemetryEndpoint(
        building_id=body.buildingId,
        endpoint_name=body.endpointName,
        endpoint_url=body.endpointUrl,
        authentication_config=body.authenticationConfig,
        endpoint_mode=body.endpointMode,
        served_zone_ids=body.servedZoneIds,
        served_room_ids=body.servedRoomIds,
        served_sensor_ids=body.servedSensorIds,
        default_location_id=body.defaultLocationId,
        response_format=body.responseFormat,
        location_mapping=body.locationMapping,
        sensor_mapping=body.sensorMapping,
        normalization_profile=body.normalizationProfile,
        available_metrics=body.availableMetrics,
        http_method=body.httpMethod.upper(),
        request_headers=body.requestHeaders,
        request_body=body.requestBody,
        polling_config=body.pollingConfig,
        priority=body.priority,
        is_enabled=body.isEnabled,
    )
    db.add(ep)
    await db.flush()
    await db.refresh(ep)
    return ep.to_api_dict()


@router.put("/{endpoint_id}")
async def update_endpoint(
    endpoint_id: str,
    body: EndpointUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    ep = await db.get(TelemetryEndpoint, endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    if body.endpointMode is not None and body.endpointMode not in TelemetryEndpoint.VALID_MODES:
        raise HTTPException(status_code=422, detail="Invalid endpointMode")

    field_map = {
        "endpointName": "endpoint_name",
        "endpointUrl": "endpoint_url",
        "authenticationConfig": "authentication_config",
        "endpointMode": "endpoint_mode",
        "servedZoneIds": "served_zone_ids",
        "servedRoomIds": "served_room_ids",
        "servedSensorIds": "served_sensor_ids",
        "defaultLocationId": "default_location_id",
        "responseFormat": "response_format",
        "locationMapping": "location_mapping",
        "sensorMapping": "sensor_mapping",
        "normalizationProfile": "normalization_profile",
        "availableMetrics": "available_metrics",
        "httpMethod": "http_method",
        "requestHeaders": "request_headers",
        "requestBody": "request_body",
        "pollingConfig": "polling_config",
        "priority": "priority",
        "isEnabled": "is_enabled",
    }
    for schema_field, model_field in field_map.items():
        val = getattr(body, schema_field)
        if val is not None:
            if schema_field == "httpMethod":
                val = val.upper()
            setattr(ep, model_field, val)

    if body.isEnabled is True:
        ep.consecutive_failures = 0

    await db.flush()
    await db.refresh(ep)
    return ep.to_api_dict()


@router.delete("/{endpoint_id}", status_code=204)
async def delete_endpoint(
    endpoint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    ep = await db.get(TelemetryEndpoint, endpoint_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    await db.delete(ep)
