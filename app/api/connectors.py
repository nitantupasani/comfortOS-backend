"""
Building Connector CRUD & management API.

    GET    /connectors/{building_id}           → List connectors for a building
    POST   /connectors                          → Register a new connector
    PUT    /connectors/{connector_id}           → Update connector config
    DELETE /connectors/{connector_id}           → Remove a connector
    POST   /connectors/{connector_id}/test      → Test connection (dry-run poll)
    POST   /connectors/{connector_id}/poll-now  → Trigger immediate poll
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..api.buildings import _get_accessible_building
from ..models.user import User, UserRole
from ..models.building import Building
from ..models.building_connector import BuildingConnector
from ..schemas.connector import (
    ConnectorCreate,
    ConnectorUpdate,
    ConnectorTestResult,
    PollResult,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])

_ADMIN_FM_ROLES = (
    UserRole.admin,
    UserRole.building_facility_manager,
    UserRole.tenant_facility_manager,
)

_VALID_AUTH_TYPES = {
    "bearer_token",
    "oauth2_client_credentials",
    "mtls",
    "api_key",
    "basic_auth",
    "hmac",
}


async def _verify_building_access(
    building_id: str, user: User, db: AsyncSession
) -> Building:
    """Verify building exists AND user has access to it."""
    return await _get_accessible_building(building_id, user, db)


async def _verify_connector_access(
    connector_id: str, user: User, db: AsyncSession
) -> BuildingConnector:
    """Load connector and verify user has access to its building."""
    result = await db.execute(
        select(BuildingConnector).where(BuildingConnector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    await _verify_building_access(connector.building_id, user, db)
    return connector


@router.get("/{building_id}")
async def list_connectors(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all connectors registered for a building."""
    if user.role not in _ADMIN_FM_ROLES:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    await _verify_building_access(building_id, user, db)

    result = await db.execute(
        select(BuildingConnector)
        .where(BuildingConnector.building_id == building_id)
        .order_by(BuildingConnector.created_at.desc())
    )
    return [c.to_api_dict() for c in result.scalars().all()]


@router.post("", status_code=201)
async def create_connector(
    body: ConnectorCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new building data connector for pull-based polling."""
    if user.role not in _ADMIN_FM_ROLES:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    await _verify_building_access(body.buildingId, user, db)

    if body.authType not in _VALID_AUTH_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid authType. Must be one of: {', '.join(sorted(_VALID_AUTH_TYPES))}",
        )

    connector = BuildingConnector(
        building_id=body.buildingId,
        name=body.name,
        description=body.description,
        base_url=body.baseUrl,
        http_method=body.httpMethod.upper(),
        request_headers=body.requestHeaders,
        request_body=body.requestBody,
        auth_type=body.authType,
        auth_config=body.authConfig,
        response_mapping=body.responseMapping,
        available_metrics=body.availableMetrics,
        polling_interval_minutes=body.pollingIntervalMinutes,
        is_enabled=body.isEnabled,
    )
    db.add(connector)
    await db.commit()
    await db.refresh(connector)
    return connector.to_api_dict()


@router.put("/{connector_id}")
async def update_connector(
    connector_id: str,
    body: ConnectorUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update connector configuration."""
    if user.role not in _ADMIN_FM_ROLES:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    connector = await _verify_connector_access(connector_id, user, db)

    if body.authType is not None and body.authType not in _VALID_AUTH_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid authType. Must be one of: {', '.join(sorted(_VALID_AUTH_TYPES))}",
        )

    field_map = {
        "name": "name",
        "description": "description",
        "baseUrl": "base_url",
        "httpMethod": "http_method",
        "requestHeaders": "request_headers",
        "requestBody": "request_body",
        "authType": "auth_type",
        "authConfig": "auth_config",
        "responseMapping": "response_mapping",
        "availableMetrics": "available_metrics",
        "pollingIntervalMinutes": "polling_interval_minutes",
        "isEnabled": "is_enabled",
    }
    for schema_field, model_field in field_map.items():
        value = getattr(body, schema_field)
        if value is not None:
            if schema_field == "httpMethod":
                value = value.upper()
            setattr(connector, model_field, value)

    # Reset failure counter if re-enabling
    if body.isEnabled is True:
        connector.consecutive_failures = 0

    await db.commit()
    await db.refresh(connector)
    return connector.to_api_dict()


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a building connector."""
    if user.role not in _ADMIN_FM_ROLES:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    connector = await _verify_connector_access(connector_id, user, db)

    await db.delete(connector)
    await db.commit()


@router.post("/{connector_id}/test", response_model=ConnectorTestResult)
async def test_connector(
    connector_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test the connector by making a single poll request (dry run — no data stored)."""
    if user.role not in _ADMIN_FM_ROLES:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    connector = await _verify_connector_access(connector_id, user, db)

    from ..services.telemetry_poller import poll_single_connector
    test_result = await poll_single_connector(connector, db, dry_run=True)
    return test_result


@router.post("/{connector_id}/poll-now", response_model=PollResult)
async def poll_now(
    connector_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate poll of this connector (stores data)."""
    if user.role not in _ADMIN_FM_ROLES:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    connector = await _verify_connector_access(connector_id, user, db)

    from ..services.telemetry_poller import poll_single_connector
    poll_result = await poll_single_connector(connector, db, dry_run=False)
    return PollResult(
        connectorId=connector.id,
        success=poll_result.success,
        readingsIngested=poll_result.readingsFound if poll_result.success else 0,
        error=poll_result.error,
    )
