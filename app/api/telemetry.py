"""
Telemetry API -- sensor data ingestion and query.

Ingestion (building services push data):
    POST /telemetry/ingest  -> Batch-push sensor readings (API-key auth)

Query (frontend reads aggregated time-series):
    GET  /telemetry/{building_id}/series  -> Time-series by metric type
    GET  /telemetry/{building_id}/latest  -> Latest reading per location
    GET  /telemetry/{building_id}/metrics -> Available metric types
    GET  /telemetry/{building_id}/room-summary -> Aggregated room-level values

Config:
    GET  /telemetry/{building_id}/config       -> List metric configs
    POST /telemetry/{building_id}/config       -> Create/update metric config
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Header
import re

import sqlalchemy as sa
from sqlalchemy import select, func, distinct, text, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..api.deps import get_current_user
from ..models.user import User, UserRole
from ..models.building import Building
from ..models.building_config import BuildingConfig
from ..models.telemetry import TelemetryReading
from ..models.location import Location
from ..models.building_telemetry_config import BuildingTelemetryConfig
from ..schemas.telemetry import (
    TelemetryBatchRequest,
    TelemetryBatchResponse,
    TelemetryQueryResponse,
    TelemetrySeriesGroup,
    TelemetryPoint,
    TelemetryRoomSummary,
    BuildingTelemetryConfigIn,
)
from ..services.ingestion import ingestion_service

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

_MAX_BATCH = 1000
_ADMIN_FM = (UserRole.admin, UserRole.building_facility_manager, UserRole.tenant_facility_manager)


# -- Helpers ---------------------------------------------------------------

async def _verify_building(building_id: str, db: AsyncSession) -> Building:
    result = await db.execute(select(Building).where(Building.id == building_id))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status_code=404, detail="Building not found")
    return building


async def _get_building_api_key(building_id: str, db: AsyncSession) -> str | None:
    result = await db.execute(
        select(BuildingConfig)
        .where(BuildingConfig.building_id == building_id, BuildingConfig.is_active == True)  # noqa: E712
        .order_by(BuildingConfig.created_at.desc())
        .limit(1)
    )
    config = result.scalar_one_or_none()
    if config and config.dashboard_layout and isinstance(config.dashboard_layout, dict):
        return config.dashboard_layout.get("telemetryApiKey")
    return None


# -- Ingestion -------------------------------------------------------------

@router.post("/ingest", response_model=TelemetryBatchResponse)
async def ingest_telemetry(
    body: TelemetryBatchRequest,
    x_api_key: str = Header(..., alias="X-Api-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Batch-ingest sensor readings from a building service.

    Uses the normalized ingestion pipeline.  All readings pass through
    location resolution, sensor resolution, unit inference, range
    validation, and quality flagging before storage.
    """
    await _verify_building(body.buildingId, db)

    expected_key = await _get_building_api_key(body.buildingId, db)
    if not expected_key:
        raise HTTPException(
            status_code=403,
            detail="Telemetry ingestion not configured. Set telemetryApiKey in building config.",
        )
    if x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    accepted, rejected, errors = await ingestion_service.normalize_and_store(
        db=db,
        building_id=body.buildingId,
        readings=body.readings[:_MAX_BATCH],
    )

    return TelemetryBatchResponse(
        accepted=accepted,
        rejected=rejected,
        buildingId=body.buildingId,
        errors=errors,
    )


# -- Query: metrics --------------------------------------------------------

@router.get("/{building_id}/metrics")
async def list_metrics(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_building(building_id, db)
    result = await db.execute(
        select(
            distinct(TelemetryReading.metric_type),
            func.min(TelemetryReading.unit),
        )
        .where(TelemetryReading.building_id == building_id)
        .group_by(TelemetryReading.metric_type)
    )
    return [{"metricType": row[0], "unit": row[1] or ""} for row in result.all()]


# -- Query: grouping levels ------------------------------------------------

@router.get("/{building_id}/grouping-levels")
async def get_grouping_levels(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return which grouping levels are available for this building.

    Analyzes the building's existing telemetry data to determine which
    hierarchy levels (room, floor, wing) are meaningful for grouping.

    HHS (all on floor "0"):        returns [room]
    Building 28 (multi-floor/wing): returns [room, floor, wing]
    """
    await _verify_building(building_id, db)

    # Get distinct floor and zone values
    result = await db.execute(
        select(
            distinct(TelemetryReading.floor),
        )
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.floor.isnot(None),
        )
    )
    floors = [r[0] for r in result.all() if r[0]]

    result = await db.execute(
        select(
            distinct(TelemetryReading.zone),
        )
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.zone.isnot(None),
        )
    )
    zones = [r[0] for r in result.all() if r[0]]

    levels = [{"key": "room", "label": "Room / Zone"}]

    # Floor is meaningful if there are multiple distinct floor values
    # or if the single floor is not "0" (which is a placeholder)
    meaningful_floors = [f for f in floors if f not in ("0", "", "default")]
    if len(meaningful_floors) > 1:
        levels.append({"key": "floor", "label": "Floor"})

    # Wing is available if zones follow the pattern "{floor}-{wing}-{room}"
    wing_pattern = re.compile(r"^\d+-([A-Za-z]+)-\d+$")
    wings = set()
    for z in zones:
        m = wing_pattern.match(z)
        if m:
            wings.add(m.group(1))
    if len(wings) > 1:
        levels.append({"key": "wing", "label": "Wing"})

    return {
        "buildingId": building_id,
        "levels": levels,
        "floors": sorted(meaningful_floors),
        "wings": sorted(wings) if wings else [],
        "roomCount": len(zones),
    }


# -- Query: time-series ----------------------------------------------------

@router.get("/{building_id}/series", response_model=TelemetryQueryResponse)
async def query_series(
    building_id: str,
    metricType: str = Query(...),
    dateFrom: str | None = Query(None),
    dateTo: str | None = Query(None),
    granularity: str = Query("hourly", description="raw | hourly | daily"),
    groupBy: str = Query("room", description="room | floor | wing"),
    locationId: str | None = Query(None, description="Filter to specific location"),
    # Legacy params
    floor: str | None = Query(None),
    zone: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query time-series sensor data, optionally aggregated.

    groupBy controls how series are grouped:
      - room (default): one series per floor/zone combo
      - floor: one series per floor, averaging across zones
      - wing: one series per wing (extracted from zone pattern "{floor}-{wing}-{room}")
    """
    await _verify_building(building_id, db)

    dt_from, dt_to = _parse_date_range(dateFrom, dateTo)

    conditions = [
        TelemetryReading.building_id == building_id,
        TelemetryReading.metric_type == metricType,
        TelemetryReading.recorded_at >= dt_from,
        TelemetryReading.recorded_at < dt_to,
    ]
    if locationId:
        conditions.append(TelemetryReading.location_id == locationId)
    if floor:
        conditions.append(TelemetryReading.floor == floor)
    if zone:
        conditions.append(TelemetryReading.zone == zone)

    if granularity in ("hourly", "daily"):
        trunc = "hour" if granularity == "hourly" else "day"

        # Determine grouping columns based on groupBy parameter
        if groupBy == "floor":
            group_cols = [TelemetryReading.floor]
            label_expr = TelemetryReading.floor
        elif groupBy == "wing":
            # Extract wing letter from zone pattern like "1-W-560" using SQL
            # split_part(zone, '-', 2) extracts the wing part
            wing_expr = func.split_part(TelemetryReading.zone, '-', 2)
            group_cols = [wing_expr]
            label_expr = wing_expr
        else:
            # Default: group by room (floor + zone)
            group_cols = [TelemetryReading.floor, TelemetryReading.zone]
            label_expr = None  # handled in response builder

        if groupBy in ("floor", "wing"):
            stmt = (
                select(
                    func.date_trunc(trunc, TelemetryReading.recorded_at).label("bucket"),
                    label_expr.label("group_key"),
                    func.round(func.avg(TelemetryReading.value).cast(sa.Numeric), 2).label("avg_val"),
                    func.min(TelemetryReading.unit).label("unit"),
                )
                .where(*conditions)
                .group_by(text("1"), text("2"))
                .order_by(text("1"))
            )
            result = await db.execute(stmt)
            rows = result.all()

            # Fetch zone→group mapping so the frontend can tie votes to groups
            zone_map_stmt = (
                select(
                    distinct(TelemetryReading.zone),
                    label_expr.label("group_key"),
                )
                .where(*conditions)
                .where(TelemetryReading.zone.isnot(None))
            )
            zone_map_result = await db.execute(zone_map_stmt)
            group_zones: dict[str, list[str]] = {}
            for zone_val, grp_key in zone_map_result.all():
                gk = grp_key or "Unknown"
                if groupBy == "floor":
                    gk = f"Floor {gk}" if gk not in ("0", "") else "Building"
                elif groupBy == "wing":
                    gk = f"Wing {gk}" if gk and gk != "" else "Unknown"
                group_zones.setdefault(gk, []).append(zone_val)

            return _build_grouped_series_response(building_id, metricType, granularity, groupBy, rows, group_zones)
        else:
            stmt = (
                select(
                    func.date_trunc(trunc, TelemetryReading.recorded_at).label("bucket"),
                    TelemetryReading.location_id,
                    TelemetryReading.floor,
                    TelemetryReading.zone,
                    func.round(func.avg(TelemetryReading.value).cast(sa.Numeric), 2).label("avg_val"),
                    func.min(TelemetryReading.unit).label("unit"),
                )
                .where(*conditions)
                .group_by(text("1"), TelemetryReading.location_id, TelemetryReading.floor, TelemetryReading.zone)
                .order_by(text("1"))
            )
            result = await db.execute(stmt)
            rows = result.all()
            loc_names = await _location_name_map(db, rows)
            return _build_series_response(building_id, metricType, granularity, rows, aggregated=True, location_names=loc_names)

    # Raw — but when grouping by floor/wing, apply 5-minute bucketed
    # averaging to avoid zigzag artifacts from interleaved room readings.
    if groupBy in ("floor", "wing"):
        # 5-minute bucket: floor epoch to nearest 300s, convert back
        bucket_expr = func.to_timestamp(
            func.floor(func.extract('epoch', TelemetryReading.recorded_at) / 300) * 300
        )
        if groupBy == "floor":
            label_expr = TelemetryReading.floor
        else:
            label_expr = func.split_part(TelemetryReading.zone, '-', 2)

        stmt = (
            select(
                bucket_expr.label("bucket"),
                label_expr.label("group_key"),
                func.round(func.avg(TelemetryReading.value).cast(sa.Numeric), 2).label("avg_val"),
                func.min(TelemetryReading.unit).label("unit"),
            )
            .where(*conditions)
            .group_by(text("1"), text("2"))
            .order_by(text("1"))
        )
        result = await db.execute(stmt)
        rows = result.all()

        zone_map_stmt = (
            select(
                distinct(TelemetryReading.zone),
                label_expr.label("group_key"),
            )
            .where(*conditions)
            .where(TelemetryReading.zone.isnot(None))
        )
        zone_map_result = await db.execute(zone_map_stmt)
        group_zones: dict[str, list[str]] = {}
        for zone_val, grp_key in zone_map_result.all():
            gk = grp_key or "Unknown"
            if groupBy == "floor":
                gk = f"Floor {gk}" if gk not in ("0", "") else "Building"
            elif groupBy == "wing":
                gk = f"Wing {gk}" if gk and gk != "" else "Unknown"
            group_zones.setdefault(gk, []).append(zone_val)

        return _build_grouped_series_response(building_id, metricType, "raw", groupBy, rows, group_zones)

    # Raw room-level — no aggregation needed, each room is its own line
    stmt = (
        select(TelemetryReading)
        .where(*conditions)
        .order_by(TelemetryReading.recorded_at)
        .limit(50_000)
    )
    result = await db.execute(stmt)
    readings = result.scalars().all()
    loc_names = await _location_name_map(db, readings)
    return _build_raw_response(building_id, metricType, readings, groupBy=groupBy, location_names=loc_names)


# -- Query: latest ---------------------------------------------------------

@router.get("/{building_id}/latest")
async def get_latest(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent reading per metric type per location."""
    await _verify_building(building_id, db)
    now = datetime.now(timezone.utc)

    subq = (
        select(
            TelemetryReading.metric_type,
            TelemetryReading.location_id,
            func.max(TelemetryReading.recorded_at).label("max_ts"),
        )
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.recorded_at <= now,
        )
        .group_by(TelemetryReading.metric_type, TelemetryReading.location_id)
        .subquery()
    )

    stmt = (
        select(TelemetryReading)
        .join(
            subq,
            (TelemetryReading.metric_type == subq.c.metric_type)
            & (
                (TelemetryReading.location_id == subq.c.location_id)
                | (TelemetryReading.location_id.is_(None) & subq.c.location_id.is_(None))
            )
            & (TelemetryReading.recorded_at == subq.c.max_ts),
        )
        .where(TelemetryReading.building_id == building_id)
    )
    result = await db.execute(stmt)
    return [r.to_api_dict() for r in result.scalars().all()]


# -- Query: room summary --------------------------------------------------

@router.get("/{building_id}/room-summary")
async def room_summary(
    building_id: str,
    metricType: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated room-level values for a metric type.

    Applies the building's room_aggregation_rule to produce one value
    per room from all sensors in that room.
    """
    await _verify_building(building_id, db)

    # Load config
    config_result = await db.execute(
        select(BuildingTelemetryConfig)
        .where(
            BuildingTelemetryConfig.building_id == building_id,
            BuildingTelemetryConfig.metric_type == metricType,
        )
    )
    config = config_result.scalar_one_or_none()
    agg_rule = config.room_aggregation_rule if config else "avg"
    stale_minutes = config.stale_threshold_minutes if config else None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    # Get latest readings per location
    stmt = (
        select(
            TelemetryReading.location_id,
            func.round(func.avg(TelemetryReading.value).cast(sa.Numeric), 2).label("avg_val"),
            func.min(TelemetryReading.value).label("min_val"),
            func.max(TelemetryReading.value).label("max_val"),
            func.max(TelemetryReading.recorded_at).label("latest_ts"),
            func.min(TelemetryReading.unit).label("unit"),
            func.count().label("sensor_count"),
        )
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.metric_type == metricType,
            TelemetryReading.recorded_at >= cutoff,
            TelemetryReading.location_id.isnot(None),
            TelemetryReading.quality_flag.in_(["good", "suspect"]),
        )
        .group_by(TelemetryReading.location_id)
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Load location names
    loc_ids = [r.location_id for r in rows if r.location_id]
    loc_names = {}
    loc_types = {}
    if loc_ids:
        loc_result = await db.execute(
            select(Location.id, Location.name, Location.type)
            .where(Location.id.in_(loc_ids))
        )
        for lid, lname, ltype in loc_result.all():
            loc_names[lid] = lname
            loc_types[lid] = ltype

    summaries = []
    for r in rows:
        # Pick value based on aggregation rule
        if agg_rule == "min":
            value = float(r.min_val)
        elif agg_rule == "max":
            value = float(r.max_val)
        else:
            value = float(r.avg_val)

        is_stale = False
        if stale_minutes and r.latest_ts:
            is_stale = r.latest_ts < now - timedelta(minutes=stale_minutes)

        summaries.append(TelemetryRoomSummary(
            locationId=r.location_id,
            locationName=loc_names.get(r.location_id, ""),
            locationType=loc_types.get(r.location_id, ""),
            metricType=metricType,
            value=value,
            unit=r.unit or "",
            recordedAt=r.latest_ts.isoformat() if r.latest_ts else "",
            aggregationMethod=agg_rule,
            sensorCount=r.sensor_count,
            qualityFlag="good",
            isStale=is_stale,
        ))

    return summaries


# -- Config ----------------------------------------------------------------

@router.get("/{building_id}/config")
async def list_telemetry_config(
    building_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_building(building_id, db)
    result = await db.execute(
        select(BuildingTelemetryConfig)
        .where(BuildingTelemetryConfig.building_id == building_id)
    )
    return [c.to_api_dict() for c in result.scalars().all()]


@router.post("/{building_id}/config", status_code=201)
async def upsert_telemetry_config(
    building_id: str,
    body: BuildingTelemetryConfigIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _ADMIN_FM:
        raise HTTPException(status_code=403, detail="Admin or FM only")

    await _verify_building(building_id, db)

    # Upsert
    result = await db.execute(
        select(BuildingTelemetryConfig)
        .where(
            BuildingTelemetryConfig.building_id == building_id,
            BuildingTelemetryConfig.metric_type == body.metricType,
        )
    )
    config = result.scalar_one_or_none()

    if config:
        config.is_enabled = body.isEnabled
        config.default_unit = body.defaultUnit
        config.source_level = body.sourceLevel
        config.room_aggregation_rule = body.roomAggregationRule
        config.preferred_sensor_id = body.preferredSensorId
        config.valid_range_min = body.validRangeMin
        config.valid_range_max = body.validRangeMax
        config.stale_threshold_minutes = body.staleThresholdMinutes
        config.conflict_resolution = body.conflictResolution
        config.connector_priority = body.connectorPriority
        config.metadata_ = body.metadata
    else:
        config = BuildingTelemetryConfig(
            building_id=building_id,
            metric_type=body.metricType,
            is_enabled=body.isEnabled,
            default_unit=body.defaultUnit,
            source_level=body.sourceLevel,
            room_aggregation_rule=body.roomAggregationRule,
            preferred_sensor_id=body.preferredSensorId,
            valid_range_min=body.validRangeMin,
            valid_range_max=body.validRangeMax,
            stale_threshold_minutes=body.staleThresholdMinutes,
            conflict_resolution=body.conflictResolution,
            connector_priority=body.connectorPriority,
            metadata_=body.metadata,
        )
        db.add(config)

    await db.flush()
    await db.refresh(config)
    return config.to_api_dict()


# -- Helpers ---------------------------------------------------------------

def _parse_date_range(
    date_from: str | None, date_to: str | None,
) -> tuple[datetime, datetime]:
    dt_from = None
    dt_to = None
    if date_from:
        dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
    if date_to:
        dt_to = (datetime.fromisoformat(date_to) + timedelta(days=1)).replace(tzinfo=timezone.utc)
    if dt_from is None and dt_to is None:
        dt_to = datetime.now(timezone.utc)
        dt_from = dt_to - timedelta(days=7)
    elif dt_from is None:
        dt_from = dt_to - timedelta(days=7)
    elif dt_to is None:
        dt_to = datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    if dt_to > now:
        dt_to = now
    return dt_from, dt_to


def _extract_wing(zone: str | None) -> str:
    """Extract wing letter from zone pattern like '1-W-560' -> 'W'."""
    if not zone:
        return "Unknown"
    parts = zone.split("-")
    if len(parts) >= 2 and parts[1].isalpha():
        return f"Wing {parts[1]}"
    return zone


def _group_key_for(r, groupBy: str) -> str:
    """Compute grouping key for a raw reading based on groupBy level."""
    if groupBy == "floor":
        return f"Floor {r.floor}" if r.floor and r.floor not in ("0", "") else "Building"
    elif groupBy == "wing":
        return _extract_wing(r.zone)
    else:
        # room level: use existing label logic
        floor = r.floor
        zone = r.zone
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


async def _location_name_map(db: AsyncSession, rows) -> dict[str, str]:
    """Build {location_id: name} map for all location_ids found in rows."""
    loc_ids = {getattr(r, "location_id", None) for r in rows}
    loc_ids.discard(None)
    if not loc_ids:
        return {}
    result = await db.execute(
        select(Location.id, Location.name).where(Location.id.in_(loc_ids))
    )
    return {lid: lname for lid, lname in result.all()}


def _build_grouped_series_response(
    building_id: str, metric_type: str, granularity: str, group_by: str, rows,
    group_zones: dict[str, list[str]] | None = None,
) -> TelemetryQueryResponse:
    """Build response for floor-level or wing-level grouping."""
    unit = rows[0].unit if rows else ""
    gz = group_zones or {}
    groups: dict[str, list] = {}
    for r in rows:
        key = r.group_key or "Unknown"
        if group_by == "floor":
            key = f"Floor {key}" if key not in ("0", "") else "Building"
        elif group_by == "wing":
            key = f"Wing {key}" if key and key != "" else "Unknown"
        groups.setdefault(key, []).append(r)

    series = []
    for key, grp in sorted(groups.items()):
        points = [
            TelemetryPoint(
                recordedAt=r.bucket.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                value=float(r.avg_val),
            )
            for r in grp
        ]
        series.append(TelemetrySeriesGroup(
            label=key,
            zones=sorted(gz.get(key, [])),
            points=points,
        ))

    return TelemetryQueryResponse(
        buildingId=building_id,
        metricType=metric_type,
        unit=unit,
        granularity=granularity,
        series=series,
    )


def _build_series_response(
    building_id: str, metric_type: str, granularity: str, rows, aggregated: bool,
    location_names: dict[str, str] | None = None,
) -> TelemetryQueryResponse:
    unit = rows[0].unit if rows else ""
    loc_names = location_names or {}
    groups: dict[str, list] = {}
    for r in rows:
        key = r.location_id or r.floor or r.zone or "Building"
        groups.setdefault(key, []).append(r)

    series = []
    for key, grp in sorted(groups.items()):
        points = [
            TelemetryPoint(
                recordedAt=r.bucket.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                value=float(r.avg_val),
                locationId=r.location_id,
                floor=r.floor,
                zone=r.zone,
            )
            for r in grp
        ]
        label = loc_names.get(key, key)
        zone_val = grp[0].zone
        series.append(TelemetrySeriesGroup(
            label=label,
            locationId=grp[0].location_id,
            locationName=loc_names.get(grp[0].location_id),
            zones=[zone_val] if zone_val else [],
            floor=grp[0].floor,
            zone=zone_val,
            points=points,
        ))

    return TelemetryQueryResponse(
        buildingId=building_id,
        metricType=metric_type,
        unit=unit,
        granularity=granularity,
        series=series,
    )


def _build_raw_response(
    building_id: str, metric_type: str, readings: list[TelemetryReading],
    groupBy: str = "room",
    location_names: dict[str, str] | None = None,
) -> TelemetryQueryResponse:
    unit = readings[0].unit if readings else ""
    loc_names = location_names or {}
    groups: dict[str, list[TelemetryReading]] = {}
    for r in readings:
        key = _group_key_for(r, groupBy)
        groups.setdefault(key, []).append(r)

    series = []
    for key, grp in sorted(groups.items()):
        points = [
            TelemetryPoint(
                recordedAt=r.recorded_at.isoformat(),
                value=round(r.value, 2),
                locationId=r.location_id,
                sensorId=r.sensor_id,
                qualityFlag=r.quality_flag,
                floor=r.floor,
                zone=r.zone,
            )
            for r in grp
        ]
        loc_id = grp[0].location_id
        zone_val = grp[0].zone
        label = loc_names.get(loc_id, key) if loc_id else key
        series.append(TelemetrySeriesGroup(
            label=label,
            locationId=loc_id,
            locationName=loc_names.get(loc_id) if loc_id else None,
            zones=[zone_val] if zone_val else [],
            floor=grp[0].floor,
            zone=zone_val,
            points=points,
        ))

    return TelemetryQueryResponse(
        buildingId=building_id,
        metricType=metric_type,
        unit=unit,
        granularity="raw",
        series=series,
    )
