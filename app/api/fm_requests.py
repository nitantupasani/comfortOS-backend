"""
FM Role Request API routes.

    POST   /fm-requests              → Submit a request (any authenticated user)
    GET    /fm-requests              → List requests (admin: all, user: own)
    PUT    /fm-requests/{id}/review  → Admin approves or rejects
    PUT    /fm-requests/{id}/revoke  → Admin revokes approved FM access
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user, require_role
from ..models.user import User, UserRole
from ..models.building import Building
from ..models.fm_request import FMRoleRequest, FMRequestStatus
from ..models.user_building_access import UserBuildingAccess
from ..schemas.fm_request import FMRequestCreate, FMRequestResponse, FMRequestReview

router = APIRouter(prefix="/fm-requests", tags=["fm-requests"])


def _to_response(r: FMRoleRequest) -> FMRequestResponse:
    return FMRequestResponse(
        id=r.id,
        userId=r.user_id,
        userEmail=r.user.email if r.user else "",
        userName=r.user.name if r.user else "",
        buildingId=r.building_id,
        buildingName=r.building.name if r.building else "",
        roleRequested=r.role_requested,
        message=r.message,
        status=r.status.value,
        reviewedBy=r.reviewed_by,
        reviewNote=r.review_note,
        createdAt=r.created_at.isoformat() if r.created_at else "",
        reviewedAt=r.reviewed_at.isoformat() if r.reviewed_at else None,
    )


@router.post("", response_model=FMRequestResponse, status_code=201)
async def create_fm_request(
    body: FMRequestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a request to become a Facility Manager for a building."""
    # Validate building exists
    result = await db.execute(select(Building).where(Building.id == body.buildingId))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    # Enforce single pending request at a time (any building)
    existing = await db.execute(
        select(FMRoleRequest).where(
            FMRoleRequest.user_id == user.id,
            FMRoleRequest.status == FMRequestStatus.pending,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending FM request. Only one pending request is allowed at a time.",
        )

    # Validate role requested
    valid_roles = {"building_facility_manager", "tenant_facility_manager"}
    role_req = body.roleRequested if body.roleRequested in valid_roles else "building_facility_manager"

    req = FMRoleRequest(
        user_id=user.id,
        building_id=body.buildingId,
        role_requested=role_req,
        message=body.message,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    return _to_response(req)


@router.get("", response_model=list[FMRequestResponse])
async def list_fm_requests(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List FM role requests. Admin sees all; others see only their own."""
    stmt = select(FMRoleRequest).order_by(FMRoleRequest.created_at.desc())
    if user.role != UserRole.admin:
        stmt = stmt.where(FMRoleRequest.user_id == user.id)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


@router.put("/{request_id}/review", response_model=FMRequestResponse)
async def review_fm_request(
    request_id: str,
    body: FMRequestReview,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Admin approves or rejects an FM request."""
    result = await db.execute(
        select(FMRoleRequest).where(FMRoleRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="FM request not found")

    if req.status != FMRequestStatus.pending:
        raise HTTPException(status_code=400, detail="Request already reviewed")

    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    now = datetime.now(timezone.utc)
    req.reviewed_by = user.id
    req.review_note = body.reviewNote
    req.reviewed_at = now

    if body.action == "approve":
        req.status = FMRequestStatus.approved

        # Upgrade the user's role
        target_result = await db.execute(
            select(User).where(User.id == req.user_id)
        )
        target_user = target_result.scalar_one_or_none()
        if target_user:
            target_user.role = UserRole(req.role_requested)
            # Update claims
            claims = dict(target_user.claims or {})
            scopes = claims.get("scopes", [])
            for s in ["manage_building", "view_analytics"]:
                if s not in scopes:
                    scopes.append(s)
            claims["scopes"] = scopes
            target_user.claims = claims

            # Grant building access
            existing_access = await db.execute(
                select(UserBuildingAccess).where(
                    UserBuildingAccess.user_id == req.user_id,
                    UserBuildingAccess.building_id == req.building_id,
                    UserBuildingAccess.is_active == True,  # noqa: E712
                )
            )
            if existing_access.scalar_one_or_none() is None:
                access = UserBuildingAccess(
                    user_id=req.user_id,
                    building_id=req.building_id,
                    granted_by=user.id,
                )
                db.add(access)
    else:
        req.status = FMRequestStatus.rejected

    await db.commit()
    await db.refresh(req)
    return _to_response(req)


@router.put("/{request_id}/revoke", response_model=FMRequestResponse)
async def revoke_fm_access(
    request_id: str,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Admin revokes a previously approved FM request — demotes user back to occupant."""
    result = await db.execute(
        select(FMRoleRequest).where(FMRoleRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="FM request not found")

    if req.status != FMRequestStatus.approved:
        raise HTTPException(status_code=400, detail="Only approved requests can be revoked")

    now = datetime.now(timezone.utc)
    req.status = FMRequestStatus.rejected
    req.reviewed_by = user.id
    req.review_note = "Access revoked by admin"
    req.reviewed_at = now

    # Demote the user back to occupant
    target_result = await db.execute(
        select(User).where(User.id == req.user_id)
    )
    target_user = target_result.scalar_one_or_none()
    if target_user:
        # Only demote if user has no other approved FM requests
        other_approved = await db.execute(
            select(FMRoleRequest).where(
                FMRoleRequest.user_id == req.user_id,
                FMRoleRequest.id != req.id,
                FMRoleRequest.status == FMRequestStatus.approved,
            )
        )
        if other_approved.scalar_one_or_none() is None:
            target_user.role = UserRole.occupant
            claims = dict(target_user.claims or {})
            scopes = claims.get("scopes", [])
            for s in ["manage_building", "view_analytics"]:
                if s in scopes:
                    scopes.remove(s)
            claims["scopes"] = scopes
            target_user.claims = claims

    # Deactivate building access grant
    access_result = await db.execute(
        select(UserBuildingAccess).where(
            UserBuildingAccess.user_id == req.user_id,
            UserBuildingAccess.building_id == req.building_id,
            UserBuildingAccess.is_active == True,  # noqa: E712
        )
    )
    access = access_result.scalar_one_or_none()
    if access:
        access.is_active = False

    await db.commit()
    await db.refresh(req)
    return _to_response(req)
