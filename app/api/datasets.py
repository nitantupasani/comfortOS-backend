"""
Dataset read API route — proxies to the Connector Gateway service.

    POST /datasets/read → Read external dataset
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User
from ..models.building import Building
from ..schemas.presence import DatasetReadRequest
from ..services.connector_gateway import read_dataset
from sqlalchemy import select

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/read")
async def dataset_read(
    body: DatasetReadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read an external dataset via the Connector Gateway.

    The Platform API proxies this request to the Connector Gateway service,
    which resolves the connector + dataset definitions from the Registry DB,
    fetches secrets, and makes the outbound HTTPS call.
    """
    # Tenant isolation
    building_result = await db.execute(
        select(Building).where(Building.id == body.buildingId)
    )
    building = building_result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")
    if building.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant isolation violation")

    result = await read_dataset(
        db=db,
        building_id=body.buildingId,
        dataset_key=body.datasetKey,
        params=body.params,
    )

    if result is None:
        return Response(status_code=204)
    return result
