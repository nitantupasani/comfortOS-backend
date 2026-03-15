"""
Telemetry API — building sensor data ingestion & query.

Ingestion (building services push data):
    POST /telemetry/ingest  → Batch-push sensor readings (API-key auth)

Query (frontend reads aggregated time-series):
    GET  /telemetry/{building_id}/series  → Time-series by metric type
    GET  /telemetry/{building_id}/latest  → Latest reading per floor/zone
    GET  /telemetry/{building_id}/metrics → Available metric types
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy import select, func, distinct, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.building import Building
from ..models.building_config import BuildingConfig
from ..models.telemetry import TelemetryReading
from ..schemas.telemetry import (
    TelemetryBatchRequest,
    TelemetryBatchResponse,
    TelemetryQueryResponse,
    TelemetrySeriesGroup,
    TelemetryPoint,
)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# Maximum batch size enforced at ingestion
_MAX_BATCH = 1000


# ── Helpers ───────────────────────────────────────────────────────────────

async def _verify_building_exists(building_id: str, db: AsyncSession) -> Building:
    result = await db.execute(select(Building).where(Building.id == building_id))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")
    return building


async def _get_building_api_key(building_id: str, db: AsyncSession) -> str | None:
    """Retrieve the telemetry API key from the building config metadata.

    Building admins set the key in the building config under:
      buildingConfig.telemetryApiKey
    """
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


# ── Ingestion endpoint ────────────────────────────────────────────────────

@router.post("/ingest", response_model=TelemetryBatchResponse)
async def ingest_telemetry(
    body: TelemetryBatchRequest,
    x_api_key: str = Header(..., alias="X-Api-Key", description="Building service API key"),
    db: AsyncSession = Depends(get_db),
):
    """Batch-ingest sensor readings from a building service.

    Authentication is via a per-building API key set in the building
    configuration by the admin/FM.  This keeps building-service
    integrations decoupled from user authentication.
    """
    building = await _verify_building_exists(body.buildingId, db)

    # Validate API key
    expected_key = await _get_building_api_key(body.buildingId, db)
    if not expected_key:
        raise HTTPException(
            status_code=403,
            detail="Telemetry ingestion not configured for this building. "
                   "Set telemetryApiKey in the building dashboard config.",
        )
    if x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Insert readings
    rows = []
    for r in body.readings[:_MAX_BATCH]:
        rows.append(TelemetryReading(
            building_id=body.buildingId,
            metric_type=r.metricType,
            value=r.value,
            unit=r.unit,
            floor=r.floor,
            zone=r.zone,
            recorded_at=r.recordedAt,
            metadata_=r.metadata,
        ))
    db.add_all(rows)
    await db.commit()

    return TelemetryBatchResponse(accepted=len(rows), buildingId=body.buildingId)


# ── Query endpoints ──────────────────────────────────────────────────────

@router.get("/{building_id}/metrics")
async def list_available_metrics(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List distinct metric types available for a building."""
    await _verify_building_exists(building_id, db)

    result = await db.execute(
        select(
            distinct(TelemetryReading.metric_type),
            func.min(TelemetryReading.unit),
        )
        .where(TelemetryReading.building_id == building_id)
        .group_by(TelemetryReading.metric_type)
    )
    return [
        {"metricType": row[0], "unit": row[1] or ""}
        for row in result.all()
    ]


@router.get("/{building_id}/series", response_model=TelemetryQueryResponse)
async def query_telemetry_series(
    building_id: str,
    metricType: str = Query(..., description="temperature, co2, noise, humidity"),
    dateFrom: str | None = Query(None, description="ISO date (inclusive)"),
    dateTo: str | None = Query(None, description="ISO date (inclusive)"),
    granularity: str = Query("hourly", description="raw | hourly | daily"),
    floor: str | None = Query(None, description="Filter to specific floor"),
    zone: str | None = Query(None, description="Filter to specific zone"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query time-series sensor data, optionally aggregated.

    Groups results by floor/zone.  If no floor/zone filters are set,
    returns one series per distinct floor (or one "Building" series if
    data has no floor labels).
    """
    await _verify_building_exists(building_id, db)

    # Parse dates
    dt_from = None
    dt_to = None
    if dateFrom:
        dt_from = datetime.fromisoformat(dateFrom).replace(tzinfo=timezone.utc)
    if dateTo:
        dt_to = (datetime.fromisoformat(dateTo) + timedelta(days=1)).replace(tzinfo=timezone.utc)

    # Default to last 7 days
    if dt_from is None and dt_to is None:
        dt_to = datetime.now(timezone.utc)
        dt_from = dt_to - timedelta(days=7)

    # Build base query
    stmt = (
        select(TelemetryReading)
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.metric_type == metricType,
        )
        .order_by(TelemetryReading.recorded_at)
    )
    if dt_from:
        stmt = stmt.where(TelemetryReading.recorded_at >= dt_from)
    if dt_to:
        stmt = stmt.where(TelemetryReading.recorded_at < dt_to)
    if floor:
        stmt = stmt.where(TelemetryReading.floor == floor)
    if zone:
        stmt = stmt.where(TelemetryReading.zone == zone)

    # Limit raw readings to prevent OOM
    stmt = stmt.limit(50_000)

    result = await db.execute(stmt)
    readings = result.scalars().all()

    # Determine unit from first reading
    unit = readings[0].unit if readings else ""

    # Group by floor+zone
    groups: dict[str, list[TelemetryReading]] = {}
    for r in readings:
        key = _group_key(r.floor, r.zone)
        groups.setdefault(key, []).append(r)

    # Build response series (apply granularity aggregation)
    series: list[TelemetrySeriesGroup] = []
    for key, group_readings in sorted(groups.items()):
        floor_val = group_readings[0].floor
        zone_val = group_readings[0].zone
        points = _aggregate(group_readings, granularity)
        series.append(TelemetrySeriesGroup(
            label=key,
            floor=floor_val,
            zone=zone_val,
            points=points,
        ))

    return TelemetryQueryResponse(
        buildingId=building_id,
        metricType=metricType,
        unit=unit,
        granularity=granularity,
        series=series,
    )


@router.get("/{building_id}/latest")
async def get_latest_readings(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent reading per metric type per floor/zone."""
    await _verify_building_exists(building_id, db)

    # Subquery: max recorded_at per (metric_type, floor, zone)
    subq = (
        select(
            TelemetryReading.metric_type,
            TelemetryReading.floor,
            TelemetryReading.zone,
            func.max(TelemetryReading.recorded_at).label("max_ts"),
        )
        .where(TelemetryReading.building_id == building_id)
        .group_by(
            TelemetryReading.metric_type,
            TelemetryReading.floor,
            TelemetryReading.zone,
        )
        .subquery()
    )

    stmt = (
        select(TelemetryReading)
        .join(
            subq,
            (TelemetryReading.metric_type == subq.c.metric_type)
            & (
                (TelemetryReading.floor == subq.c.floor)
                | (TelemetryReading.floor.is_(None) & subq.c.floor.is_(None))
            )
            & (
                (TelemetryReading.zone == subq.c.zone)
                | (TelemetryReading.zone.is_(None) & subq.c.zone.is_(None))
            )
            & (TelemetryReading.recorded_at == subq.c.max_ts),
        )
        .where(TelemetryReading.building_id == building_id)
    )

    result = await db.execute(stmt)
    return [r.to_api_dict() for r in result.scalars().all()]


# ── Aggregation helpers ───────────────────────────────────────────────────

def _group_key(floor: str | None, zone: str | None) -> str:
    """Stable display label for a floor+zone pair."""
    # Omit generic/placeholder floor values — just show zone
    generic_floors = {"0", "ground", "default", "-", ""}
    floor_is_generic = not floor or floor.strip().lower() in generic_floors
    if floor_is_generic and zone:
        return zone
    if floor and zone:
        return f"{floor} / {zone}"
    if floor:
        return floor
    if zone:
        return zone
    return "Building"


def _aggregate(
    readings: list[TelemetryReading],
    granularity: str,
) -> list[TelemetryPoint]:
    """Bucket readings by time and return averaged points."""
    if granularity == "raw" or len(readings) <= 1:
        return [
            TelemetryPoint(
                recordedAt=r.recorded_at.isoformat(),
                value=round(r.value, 2),
                floor=r.floor,
                zone=r.zone,
            )
            for r in readings
        ]

    # Bucket by hour or day
    bucket_fmt = "%Y-%m-%dT%H:00:00" if granularity == "hourly" else "%Y-%m-%d"
    buckets: dict[str, list[float]] = {}
    first_reading = readings[0]
    for r in readings:
        key = r.recorded_at.strftime(bucket_fmt)
        buckets.setdefault(key, []).append(r.value)

    return [
        TelemetryPoint(
            recordedAt=ts + ("+00:00" if "T" in ts else "T00:00:00+00:00"),
            value=round(sum(vals) / len(vals), 2),
            floor=first_reading.floor,
            zone=first_reading.zone,
        )
        for ts, vals in sorted(buckets.items())
    ]
