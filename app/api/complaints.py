"""
Complaints API routes.

    POST   /complaints                       → Raise a complaint (any authenticated user with building access)
    GET    /complaints?buildingId=...        → List complaints for buildings the caller can access
    GET    /complaints/{id}                  → Fetch one complaint (with comments + cosigners)
    POST   /complaints/{id}/cosign           → Add caller as co-signer (idempotent)
    DELETE /complaints/{id}/cosign           → Remove caller's co-sign
    POST   /complaints/{id}/comments         → FM/admin only: add a comment
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.building import Building
from ..models.building_tenant import BuildingTenant
from ..models.user_building_access import UserBuildingAccess
from ..models.complaint import (
    Complaint,
    ComplaintCosign,
    ComplaintComment,
    ComplaintType,
)
from ..schemas.complaint import (
    ComplaintCreate,
    ComplaintResponse,
    ComplaintCommentCreate,
    ComplaintCommentResponse,
)

router = APIRouter(prefix="/complaints", tags=["complaints"])


# ── access helpers ────────────────────────────────────────────────────────


async def _has_building_access(db: AsyncSession, user: User, building: Building) -> bool:
    """True if the user can view/act on complaints for this building."""
    if user.role in (UserRole.admin, UserRole.building_facility_manager):
        return True
    if not building.requires_access_permission:
        return True

    if user.tenant_id:
        bt = await db.execute(
            select(BuildingTenant).where(
                BuildingTenant.building_id == building.id,
                BuildingTenant.tenant_id == user.tenant_id,
                BuildingTenant.is_active == True,  # noqa: E712
            )
        )
        if bt.scalar_one_or_none() is not None:
            return True

    uba = await db.execute(
        select(UserBuildingAccess).where(
            UserBuildingAccess.user_id == user.id,
            UserBuildingAccess.building_id == building.id,
            UserBuildingAccess.is_active == True,  # noqa: E712
        )
    )
    return uba.scalar_one_or_none() is not None


async def _accessible_building_ids(db: AsyncSession, user: User) -> list[str]:
    """All building ids the user can access. Admin/building FM see all."""
    if user.role in (UserRole.admin, UserRole.building_facility_manager):
        r = await db.execute(select(Building.id))
        return [row[0] for row in r.all()]

    ids: set[str] = set()

    # Open buildings
    r = await db.execute(
        select(Building.id).where(Building.requires_access_permission == False)  # noqa: E712
    )
    ids.update(row[0] for row in r.all())

    # Tenant-mapped buildings
    if user.tenant_id:
        r = await db.execute(
            select(BuildingTenant.building_id).where(
                BuildingTenant.tenant_id == user.tenant_id,
                BuildingTenant.is_active == True,  # noqa: E712
            )
        )
        ids.update(row[0] for row in r.all())

    # Explicit access grants
    r = await db.execute(
        select(UserBuildingAccess.building_id).where(
            UserBuildingAccess.user_id == user.id,
            UserBuildingAccess.is_active == True,  # noqa: E712
        )
    )
    ids.update(row[0] for row in r.all())

    return list(ids)


def _is_fm(user: User) -> bool:
    return user.role in (
        UserRole.admin,
        UserRole.tenant_facility_manager,
        UserRole.building_facility_manager,
    )


# ── serialization ─────────────────────────────────────────────────────────


def _comment_to_response(c: ComplaintComment) -> ComplaintCommentResponse:
    return ComplaintCommentResponse(
        id=c.id,
        complaintId=c.complaint_id,
        authorId=c.author_id,
        authorName=c.author.name if c.author else "",
        authorRole=c.author.role.value if c.author else "",
        body=c.body,
        createdAt=c.created_at.isoformat() if c.created_at else "",
    )


def _to_response(c: Complaint, viewer_id: str) -> ComplaintResponse:
    cosigner_ids = [cs.user_id for cs in c.cosigners]
    return ComplaintResponse(
        id=c.id,
        buildingId=c.building_id,
        buildingName=c.building.name if c.building else "",
        createdBy=c.created_by,
        authorName=c.author.name if c.author else "",
        complaintType=c.complaint_type.value,
        title=c.title,
        description=c.description,
        createdAt=c.created_at.isoformat() if c.created_at else "",
        cosignCount=len(cosigner_ids),
        cosignerIds=cosigner_ids,
        viewerHasCosigned=viewer_id in cosigner_ids,
        comments=[_comment_to_response(cm) for cm in c.comments],
    )


async def _load_complaint(db: AsyncSession, complaint_id: str) -> Complaint:
    result = await db.execute(select(Complaint).where(Complaint.id == complaint_id))
    c = result.scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return c


# ── routes ────────────────────────────────────────────────────────────────


@router.post("", response_model=ComplaintResponse, status_code=201)
async def create_complaint(
    body: ComplaintCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Raise a complaint against a building."""
    try:
        ctype = ComplaintType(body.complaintType)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid complaintType. Must be one of: {[t.value for t in ComplaintType]}",
        )

    bres = await db.execute(select(Building).where(Building.id == body.buildingId))
    building = bres.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")

    if not await _has_building_access(db, user, building):
        raise HTTPException(status_code=403, detail="No access to this building")

    complaint = Complaint(
        building_id=body.buildingId,
        created_by=user.id,
        complaint_type=ctype,
        title=body.title.strip(),
        description=(body.description or None),
    )
    db.add(complaint)
    await db.flush()

    # Auto-cosign by creator so initial priority reflects their support.
    db.add(ComplaintCosign(complaint_id=complaint.id, user_id=user.id))
    await db.commit()

    # Reload with relationships populated for response serialization.
    fresh = await _load_complaint(db, complaint.id)
    return _to_response(fresh, user.id)


@router.get("", response_model=list[ComplaintResponse])
async def list_complaints(
    buildingId: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List complaints, sorted by cosign count desc then newest first.

    Scoped to buildings the caller can access. Optional `buildingId` filter.
    """
    accessible = await _accessible_building_ids(db, user)
    if not accessible:
        return []

    if buildingId is not None:
        if buildingId not in accessible:
            raise HTTPException(status_code=403, detail="No access to this building")
        target_ids = [buildingId]
    else:
        target_ids = accessible

    result = await db.execute(
        select(Complaint)
        .where(Complaint.building_id.in_(target_ids))
        .order_by(Complaint.created_at.desc())
    )
    rows = result.scalars().unique().all()

    responses = [_to_response(r, user.id) for r in rows]
    # Priority sort: most co-signed first, ties broken by newest.
    responses.sort(key=lambda r: (-r.cosignCount, _neg_ts(r.createdAt)))
    return responses


def _neg_ts(iso: str) -> float:
    """Secondary sort key — newest first within equal cosign counts."""
    from datetime import datetime
    try:
        return -datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


@router.get("/{complaint_id}", response_model=ComplaintResponse)
async def get_complaint(
    complaint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    complaint = await _load_complaint(db, complaint_id)
    if not await _has_building_access(db, user, complaint.building):
        raise HTTPException(status_code=403, detail="No access to this building")
    return _to_response(complaint, user.id)


@router.post("/{complaint_id}/cosign", response_model=ComplaintResponse)
async def cosign_complaint(
    complaint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add caller as a co-signer. Idempotent."""
    complaint = await _load_complaint(db, complaint_id)
    if not await _has_building_access(db, user, complaint.building):
        raise HTTPException(status_code=403, detail="No access to this building")

    existing = await db.execute(
        select(ComplaintCosign).where(
            ComplaintCosign.complaint_id == complaint_id,
            ComplaintCosign.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(ComplaintCosign(complaint_id=complaint_id, user_id=user.id))
        await db.commit()

    fresh = await _load_complaint(db, complaint_id)
    return _to_response(fresh, user.id)


@router.delete("/{complaint_id}/cosign", response_model=ComplaintResponse)
async def uncosign_complaint(
    complaint_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove caller's co-sign. Idempotent."""
    complaint = await _load_complaint(db, complaint_id)
    if not await _has_building_access(db, user, complaint.building):
        raise HTTPException(status_code=403, detail="No access to this building")

    await db.execute(
        delete(ComplaintCosign).where(
            ComplaintCosign.complaint_id == complaint_id,
            ComplaintCosign.user_id == user.id,
        )
    )
    await db.commit()

    fresh = await _load_complaint(db, complaint_id)
    return _to_response(fresh, user.id)


@router.post("/{complaint_id}/comments", response_model=ComplaintResponse, status_code=201)
async def comment_on_complaint(
    complaint_id: str,
    body: ComplaintCommentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FM or admin only: add a comment to a complaint."""
    if not _is_fm(user):
        raise HTTPException(status_code=403, detail="Only facility managers may comment on complaints")

    complaint = await _load_complaint(db, complaint_id)
    if not await _has_building_access(db, user, complaint.building):
        raise HTTPException(status_code=403, detail="No access to this building")

    db.add(ComplaintComment(
        complaint_id=complaint_id,
        author_id=user.id,
        body=body.body.strip(),
    ))
    await db.commit()

    fresh = await _load_complaint(db, complaint_id)
    return _to_response(fresh, user.id)
