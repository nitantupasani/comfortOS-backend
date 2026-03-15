"""
Presence & Notification API routes.

    POST /presence/events              → Report presence event
    GET  /presence/beacons?buildingId= → BLE beacon registry
    POST /notifications/register       → Register push token
    POST /notifications/send           → Send notification (admin)
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.presence import PresenceEvent, Beacon
from ..models.notification import PushToken
from ..models.building import Building
from ..models.building_tenant import BuildingTenant
from ..models.user_building_access import UserBuildingAccess
from ..schemas.presence import (
    PresenceEventRequest,
    PushTokenRegisterRequest,
    SendNotificationRequest,
    SendNotificationResponse,
)
from ..services.notification_service import send_to_users, send_broadcast

router = APIRouter(tags=["presence & notifications"])


# ── Presence ─────────────────────────────────────────────────────────────

@router.post("/presence/events")
async def report_presence_event(
    body: PresenceEventRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a presence check-in event."""
    # Verify building exists
    result = await db.execute(
        select(Building).where(Building.id == body.buildingId)
    )
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    # Access check: open buildings allow anyone; restricted need tenant mapping or explicit grant
    if building.requires_access_permission:
        has_access = False

        if user.tenant_id:
            bt_check = await db.execute(
                select(BuildingTenant).where(
                    BuildingTenant.building_id == body.buildingId,
                    BuildingTenant.tenant_id == user.tenant_id,
                    BuildingTenant.is_active == True,  # noqa: E712
                )
            )
            if bt_check.scalar_one_or_none() is not None:
                has_access = True

        if not has_access:
            uba_check = await db.execute(
                select(UserBuildingAccess).where(
                    UserBuildingAccess.user_id == user.id,
                    UserBuildingAccess.building_id == body.buildingId,
                    UserBuildingAccess.is_active == True,  # noqa: E712
                )
            )
            if uba_check.scalar_one_or_none() is not None:
                has_access = True

        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="This building requires access permission",
            )

    event = PresenceEvent(
        building_id=body.buildingId,
        user_id=user.id,
        method=body.method,
        confidence=body.confidence,
        is_verified=body.isVerified,
        timestamp=datetime.fromisoformat(body.timestamp)
        if body.timestamp
        else datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    return {"status": "ok"}


@router.get("/presence/beacons")
async def get_beacons(
    buildingId: str = Query(..., description="Building ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List registered BLE beacons for a building."""
    # Access check: open buildings → anyone; restricted → tenant mapping
    building_result = await db.execute(
        select(Building).where(Building.id == buildingId)
    )
    building = building_result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    if building.requires_access_permission:
        if user.role not in (UserRole.admin, UserRole.building_facility_manager):
            has_access = False

            if user.tenant_id:
                bt_check = await db.execute(
                    select(BuildingTenant).where(
                        BuildingTenant.building_id == buildingId,
                        BuildingTenant.tenant_id == user.tenant_id,
                        BuildingTenant.is_active == True,  # noqa: E712
                    )
                )
                if bt_check.scalar_one_or_none() is not None:
                    has_access = True

            if not has_access:
                uba_check = await db.execute(
                    select(UserBuildingAccess).where(
                        UserBuildingAccess.user_id == user.id,
                        UserBuildingAccess.building_id == buildingId,
                        UserBuildingAccess.is_active == True,  # noqa: E712
                    )
                )
                if uba_check.scalar_one_or_none() is not None:
                    has_access = True

            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="This building requires access permission",
                )

    result = await db.execute(
        select(Beacon).where(Beacon.building_id == buildingId)
    )
    beacons = result.scalars().all()
    return [b.to_api_dict() for b in beacons]


# ── Notifications ────────────────────────────────────────────────────────

@router.post("/notifications/register")
async def register_push_token(
    body: PushTokenRegisterRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register or update a device push token for FCM/APNs delivery."""
    # Remove existing tokens for this user (one active token per user for now)
    await db.execute(
        delete(PushToken).where(PushToken.user_id == user.id)
    )
    token = PushToken(
        user_id=user.id,
        push_token=body.pushToken,
        platform=body.platform,
    )
    db.add(token)
    await db.flush()
    return {"status": "ok"}


@router.post("/notifications/send", response_model=SendNotificationResponse)
async def send_notification(
    body: SendNotificationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a push notification via FCM/APNs (admin/manager only).

    - If ``userIds`` is provided, sends to those specific users.
    - If ``userIds`` is omitted, broadcasts to all registered devices.
    """
    if user.role.value not in (
        "tenant_facility_manager", "building_facility_manager", "admin"
    ):
        raise HTTPException(status_code=403, detail="Insufficient role")

    if body.userIds:
        result = await send_to_users(
            db, body.userIds, body.title, body.body, body.data
        )
    else:
        result = await send_broadcast(db, body.title, body.body, body.data)

    return SendNotificationResponse(
        status="sent",
        sent=result["sent"],
        failed=result["failed"],
        detail=result.get("detail"),
    )
