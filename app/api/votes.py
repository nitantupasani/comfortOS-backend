"""
Vote Ingestion API routes.

    POST /votes                  → Submit comfort vote (idempotent by voteUuid)
    GET  /votes/history?userId=  → Vote history for a user
    GET  /votes/analytics        → Building-wide vote analytics (admin/FM)
"""

from datetime import datetime, timezone, timedelta, date

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..api.buildings import _get_accessible_building
from ..models.user import User, UserRole
from ..models.vote import Vote as VoteModel, VoteStatus
from ..models.building import Building
from ..models.building_tenant import BuildingTenant
from ..models.user_building_access import UserBuildingAccess
from ..models.building_config import BuildingConfig
from ..schemas.vote import VoteSubmitRequest, VoteSubmitResponse
from ..services.gamification import (
    eco_points,
    tier_for,
    compute_streaks,
    GROWN_TREE_MIN_POINTS,
)

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

    # Normalize payload: frontend submits the occupant's current room as
    # `room`; analytics joins on `zone`. Mirror when the caller hasn't set
    # one explicitly so every vote is location-resolvable downstream.
    payload = dict(body.payload or {})
    if "zone" not in payload and payload.get("room"):
        payload["zone"] = payload["room"]

    # Create vote
    vote = VoteModel(
        vote_uuid=body.voteUuid,
        building_id=body.buildingId,
        user_id=user.id,
        payload=payload,
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
    zone: str | None = Query(None, description="Filter by zone/room name"),
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

    # Verify building exists AND user has access
    building = await _get_accessible_building(buildingId, user, db)

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

    if zone:
        # Filter votes whose JSON payload contains matching zone
        query = query.where(VoteModel.payload["zone"].as_string() == zone)

    query = query.order_by(VoteModel.created_at.desc()).limit(10000)
    result = await db.execute(query)
    votes = result.scalars().all()

    return {
        "buildingId": buildingId,
        "buildingName": building.name,
        "totalVotes": len(votes),
        "votes": [v.to_api_dict() for v in votes],
    }


@router.get("/leaderboard")
async def get_vote_leaderboard(
    buildingId: str = Query(..., description="Building ID"),
    limit: int = Query(20, ge=1, le=100, description="Max ranked rows to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Occupant contribution leaderboard for a building (gamification).

    Ranks user-attributed votes by eco-points (votes + streak bonus) and grows a
    tree tier per occupant. Feeds both the occupant Eco screen and the admin/FM
    engagement stats. Anonymous votes (``user_id IS NULL``) are excluded.

    Access: any authenticated user who may use the building. Restricted buildings
    apply the same tenant / explicit-grant check as ``submit_vote``.
    """
    # Load building
    building_result = await db.execute(
        select(Building).where(Building.id == buildingId)
    )
    building = building_result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    # Access check (mirrors submit_vote): admins / building FMs always allowed;
    # everyone else needs tenant mapping or an explicit access grant.
    if building.requires_access_permission and user.role not in (
        UserRole.admin,
        UserRole.building_facility_manager,
    ):
        has_access = False
        if user.tenant_id:
            bt_check = await db.execute(
                select(BuildingTenant).where(
                    BuildingTenant.building_id == buildingId,
                    BuildingTenant.tenant_id == user.tenant_id,
                    BuildingTenant.is_active == True,  # noqa: E712
                )
            )
            has_access = bt_check.scalar_one_or_none() is not None
        if not has_access:
            uba_check = await db.execute(
                select(UserBuildingAccess).where(
                    UserBuildingAccess.user_id == user.id,
                    UserBuildingAccess.building_id == buildingId,
                    UserBuildingAccess.is_active == True,  # noqa: E712
                )
            )
            has_access = uba_check.scalar_one_or_none() is not None
        if not has_access:
            raise HTTPException(
                status_code=403, detail="This building requires access permission"
            )

    # Vote count per user (attributed votes only)
    count_rows = await db.execute(
        select(VoteModel.user_id, func.count(VoteModel.vote_uuid))
        .where(
            VoteModel.building_id == buildingId,
            VoteModel.user_id.is_not(None),
        )
        .group_by(VoteModel.user_id)
    )
    vote_counts: dict[str, int] = {uid: cnt for uid, cnt in count_rows.all()}

    if not vote_counts:
        return {
            "buildingId": buildingId,
            "buildingName": building.name,
            "summary": {
                "totalContributors": 0,
                "totalVotes": 0,
                "totalEcoPoints": 0,
                "treesGrown": 0,
                "activeStreaks": 0,
                "topContributor": None,
            },
            "leaderboard": [],
        }

    # Distinct vote days per user → streaks
    day_rows = await db.execute(
        select(VoteModel.user_id, func.date(VoteModel.created_at))
        .where(
            VoteModel.building_id == buildingId,
            VoteModel.user_id.is_not(None),
        )
        .group_by(VoteModel.user_id, func.date(VoteModel.created_at))
    )
    user_days: dict[str, set] = {}
    for uid, day in day_rows.all():
        # func.date may return a date or an ISO string depending on driver
        if isinstance(day, str):
            day = date.fromisoformat(day)
        user_days.setdefault(uid, set()).add(day)

    # Resolve names
    user_ids = list(vote_counts.keys())
    name_rows = await db.execute(
        select(User.id, User.name).where(User.id.in_(user_ids))
    )
    names: dict[str, str] = {uid: nm for uid, nm in name_rows.all()}

    # Build entries
    entries: list[dict] = []
    for uid, votes in vote_counts.items():
        current_streak, best_streak = compute_streaks(user_days.get(uid, set()))
        points = eco_points(votes, best_streak)
        tier = tier_for(points)
        entries.append(
            {
                "userId": uid,
                "name": names.get(uid, "Unknown"),
                "votes": votes,
                "currentStreak": current_streak,
                "bestStreak": best_streak,
                "ecoPoints": points,
                "tier": tier["key"],
                "tierLabel": tier["label"],
                "nextLabel": tier["next_label"],
                "nextPoints": tier["next_points"],
                "progress": round(tier["progress"], 3),
            }
        )

    entries.sort(key=lambda e: (e["ecoPoints"], e["votes"]), reverse=True)
    for i, e in enumerate(entries, 1):
        e["rank"] = i

    summary = {
        "totalContributors": len(entries),
        "totalVotes": sum(e["votes"] for e in entries),
        "totalEcoPoints": sum(e["ecoPoints"] for e in entries),
        "treesGrown": sum(1 for e in entries if e["ecoPoints"] >= GROWN_TREE_MIN_POINTS),
        "activeStreaks": sum(1 for e in entries if e["currentStreak"] >= 2),
        "topContributor": {
            "name": entries[0]["name"],
            "ecoPoints": entries[0]["ecoPoints"],
            "tier": entries[0]["tier"],
        },
    }

    return {
        "buildingId": buildingId,
        "buildingName": building.name,
        "summary": summary,
        "leaderboard": entries[:limit],
    }


# ── Bulk anonymous vote ingest (building-service API-key auth) ────────────

async def _get_building_api_key(building_id: str, db: AsyncSession) -> str | None:
    result = await db.execute(
        select(BuildingConfig)
        .where(
            BuildingConfig.building_id == building_id,
            BuildingConfig.is_active == True,  # noqa: E712
        )
        .order_by(BuildingConfig.created_at.desc())
        .limit(1)
    )
    config = result.scalar_one_or_none()
    if config and config.dashboard_layout and isinstance(config.dashboard_layout, dict):
        return config.dashboard_layout.get("telemetryApiKey")
    return None


from pydantic import BaseModel
from typing import List


class AnonymousVote(BaseModel):
    voteUuid: str
    thermalComfort: int
    createdAt: str
    zone: str | None = None


class AnonymousVoteBatchRequest(BaseModel):
    buildingId: str
    votes: List[AnonymousVote]


class AnonymousVoteBatchResponse(BaseModel):
    accepted: int
    skipped: int


@router.post("/ingest", response_model=AnonymousVoteBatchResponse)
async def ingest_anonymous_votes(
    body: AnonymousVoteBatchRequest,
    x_api_key: str = Header(..., alias="X-Api-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-ingest anonymous comfort votes from a building service.

    Uses the same per-building telemetry API key for authentication.
    Votes are stored without a user_id (anonymous).
    """
    # Verify building
    result = await db.execute(select(Building).where(Building.id == body.buildingId))
    building = result.scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    # API key check
    expected_key = await _get_building_api_key(body.buildingId, db)
    if not expected_key:
        raise HTTPException(status_code=403, detail="Telemetry API key not configured")
    if x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    accepted = 0
    skipped = 0
    updated = 0
    for v in body.votes:
        existing_result = await db.execute(
            select(VoteModel).where(VoteModel.vote_uuid == v.voteUuid)
        )
        existing_vote = existing_result.scalar_one_or_none()
        new_ts = datetime.fromisoformat(v.createdAt.replace("Z", "+00:00"))
        new_payload = {"thermal_comfort": v.thermalComfort, **({"zone": v.zone} if v.zone else {})}
        if existing_vote is not None:
            # Update timestamp and payload if changed
            changed = False
            if existing_vote.created_at != new_ts:
                existing_vote.created_at = new_ts
                changed = True
            if existing_vote.payload != new_payload:
                existing_vote.payload = new_payload
                changed = True
            if changed:
                updated += 1
            else:
                skipped += 1
            continue
        vote = VoteModel(
            vote_uuid=v.voteUuid,
            building_id=body.buildingId,
            user_id=None,
            payload=new_payload,
            schema_version=1,
            status=VoteStatus.confirmed,
            created_at=new_ts,
        )
        db.add(vote)
        accepted += 1

    await db.flush()
    return AnonymousVoteBatchResponse(accepted=accepted + updated, skipped=skipped)
