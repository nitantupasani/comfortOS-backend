"""
Vote Ingestion API routes.

    POST /votes                  → Submit comfort vote (idempotent by voteUuid)
    GET  /votes/history?userId=  → Vote history for a user
    GET  /votes/analytics        → Building-wide vote analytics (admin/FM)
"""

from datetime import datetime, timezone, timedelta, date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.vote import Vote as VoteModel, VoteStatus
from ..models.building import Building
from ..models.building_tenant import BuildingTenant
from ..models.user_building_access import UserBuildingAccess
from ..schemas.vote import VoteSubmitRequest, VoteSubmitResponse

router = APIRouter(prefix="/votes", tags=["votes"])

DAILY_VOTE_LIMIT = 10  # max votes a single occupant may submit per calendar day


async def _check_daily_vote_limit(
    user_id: str, building_id: str, db: AsyncSession
) -> None:
    """Raise 429 if the user has already reached the per-user daily vote cap."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = await db.execute(
        select(func.count(VoteModel.vote_uuid)).where(
            VoteModel.user_id == user_id,
            VoteModel.building_id == building_id,
            VoteModel.created_at >= today_start,
        )
    )
    count = result.scalar() or 0
    if count >= DAILY_VOTE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Daily vote limit reached ({DAILY_VOTE_LIMIT} votes/day)",
        )


@router.post("", response_model=VoteSubmitResponse)
async def submit_vote(
    body: VoteSubmitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a comfort vote. Idempotent by voteUuid.

    Access rules
    ------------
    - **Open buildings** — any authenticated user may vote (subject to the
      per-user daily vote limit on the building).
    - **Restricted buildings** — the user's tenant must be mapped to the
      building via ``building_tenants``.
    """
    # Check idempotency
    existing = await db.execute(
        select(VoteModel).where(VoteModel.vote_uuid == body.voteUuid)
    )
    if existing.scalar_one_or_none() is not None:
        return VoteSubmitResponse(status="already_accepted", voteUuid=body.voteUuid)

    # Load building
    building_result = await db.execute(
        select(Building).where(Building.id == body.buildingId)
    )
    building = building_result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    # Access check
    if building.requires_access_permission:
        # Admins and building FMs always have access
        if user.role in (UserRole.admin, UserRole.building_facility_manager):
            pass  # always allowed
        else:
            has_access = False

            # Check tenant-based access
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

            # Check explicit access grant
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

    # Per-user daily vote rate limit
    await _check_daily_vote_limit(user.id, body.buildingId, db)

    # Create vote
    vote = VoteModel(
        vote_uuid=body.voteUuid,
        building_id=body.buildingId,
        user_id=user.id,
        payload=body.payload,
        schema_version=body.schemaVersion,
        status=VoteStatus.confirmed,
        created_at=datetime.fromisoformat(body.createdAt.replace("Z", "+00:00"))
        if body.createdAt
        else datetime.now(timezone.utc),
    )
    db.add(vote)
    await db.flush()

    return VoteSubmitResponse(status="accepted", voteUuid=body.voteUuid)


@router.get("/history")
async def get_vote_history(
    userId: str = Query(..., description="User ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve vote history for a user. Users can only see their own votes
    unless they are a manager or admin.
    """
    # Occupants can only see their own history; FMs and admins can see others
    if user.role == UserRole.occupant and user.id != userId:
        raise HTTPException(status_code=403, detail="Cannot view other users' votes")

    result = await db.execute(
        select(VoteModel)
        .where(VoteModel.user_id == userId)
        .order_by(VoteModel.created_at.desc())
        .limit(100)
    )
    votes = result.scalars().all()
    return [v.to_api_dict() for v in votes]


@router.get("/analytics")
async def get_vote_analytics(
    buildingId: str = Query(..., description="Building ID"),
    dateFrom: str | None = Query(None, description="Start date (ISO format)"),
    dateTo: str | None = Query(None, description="End date (ISO format)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all votes for a building, for analytics dashboards.

    Access: admin and facility-manager roles only.
    Supports optional date-range filtering via ``dateFrom`` / ``dateTo``.
    """
    # Role gate
    if user.role not in (
        UserRole.admin,
        UserRole.building_facility_manager,
        UserRole.tenant_facility_manager,
    ):
        raise HTTPException(status_code=403, detail="Analytics requires FM or admin role")

    # Verify building exists
    building_result = await db.execute(
        select(Building).where(Building.id == buildingId)
    )
    building = building_result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    # Build query
    query = select(VoteModel).where(VoteModel.building_id == buildingId)

    if dateFrom:
        try:
            dt_from = datetime.fromisoformat(dateFrom).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid dateFrom format")
        query = query.where(VoteModel.created_at >= dt_from)

    if dateTo:
        try:
            dt_to = datetime.fromisoformat(dateTo).replace(tzinfo=timezone.utc)
            # Include the full end day
            dt_to = dt_to.replace(hour=23, minute=59, second=59)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid dateTo format")
        query = query.where(VoteModel.created_at <= dt_to)

    query = query.order_by(VoteModel.created_at.desc()).limit(10000)
    result = await db.execute(query)
    votes = result.scalars().all()

    return {
        "buildingId": buildingId,
        "buildingName": building.name,
        "totalVotes": len(votes),
        "votes": [v.to_api_dict() for v in votes],
    }
