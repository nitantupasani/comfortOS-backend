"""Tools exposed to the ComfortOS AI building persona via Gemini function calling.

Each tool is a plain async function that takes a DB session + already-validated
context (user, building_id) plus keyword arguments from the model, and returns
a JSON-serialisable dict. Tool declarations describe them to Gemini.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from google.genai import types
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.complaint import Complaint, ComplaintCosign, ComplaintType
from ..models.location import Location
from ..models.telemetry import TelemetryReading
from ..models.user import User
from ..models.vote import Vote


# ──────────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────────


async def tool_get_current_temperature(
    db: AsyncSession, building_id: str, floor: str | None = None, **_: Any,
) -> dict:
    """Current (live) temperature per room for the building, plus a building-wide average.

    Uses each sensor's MOST RECENT reading (not a 24h time-average), so the
    numbers match the dashboard's live room cards. Filters out bad-quality and
    null-location rows, collapses placement-level rows into their parent room,
    and averages co-located sensors within each room (spatial only, never over
    time). A 24h freshness window drops dead/stale sensors.

    Each reading carries its floor. Pass `floor` (a name or code substring, e.g.
    "2", "2e", "Begane grond") to restrict the result — including warmest,
    coolest, and the average — to rooms on matching floors. Omit it for the
    whole building.
    """
    from collections import defaultdict
    from ..api.telemetry import _resolve_placements_to_rooms

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    # Most recent timestamp per sensor location, within the freshness window.
    latest_ts_subq = (
        select(
            TelemetryReading.location_id.label("location_id"),
            func.max(TelemetryReading.recorded_at).label("max_ts"),
        )
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.metric_type == "temperature",
            TelemetryReading.recorded_at >= cutoff,
            TelemetryReading.recorded_at <= now,
            TelemetryReading.location_id.isnot(None),
            TelemetryReading.quality_flag.in_(["good", "suspect"]),
        )
        .group_by(TelemetryReading.location_id)
        .subquery()
    )

    # Pull the actual latest reading (value + unit) for each sensor location.
    stmt = (
        select(
            TelemetryReading.location_id,
            TelemetryReading.value,
            TelemetryReading.recorded_at,
            TelemetryReading.unit,
        )
        .join(
            latest_ts_subq,
            (TelemetryReading.location_id == latest_ts_subq.c.location_id)
            & (TelemetryReading.recorded_at == latest_ts_subq.c.max_ts),
        )
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.metric_type == "temperature",
        )
    )
    raw_rows = (await db.execute(stmt)).all()
    if not raw_rows:
        return {"ok": False, "reason": "No temperature readings in the last 24 hours."}

    # Dedupe to one latest reading per sensor (ties on identical timestamps).
    per_sensor: dict[str, Any] = {}
    for r in raw_rows:
        prev = per_sensor.get(r.location_id)
        if prev is None or r.recorded_at > prev.recorded_at:
            per_sensor[r.location_id] = r
    rows = list(per_sensor.values())

    loc_ids = {r.location_id for r in rows}
    room_map = await _resolve_placements_to_rooms(db, loc_ids)

    per_room_vals: dict[str, list[float]] = defaultdict(list)
    per_room_latest: dict[str, datetime] = {}
    per_room_unit: dict[str, str] = {}
    for r in rows:
        rid = room_map.get(r.location_id, r.location_id)
        per_room_vals[rid].append(float(r.value))
        if rid not in per_room_latest or r.recorded_at > per_room_latest[rid]:
            per_room_latest[rid] = r.recorded_at
        per_room_unit[rid] = r.unit or "C"

    name_rows = (
        await db.execute(
            select(Location.id, Location.name).where(Location.id.in_(per_room_vals.keys()))
        )
    ).all()
    names = {lid: ln for lid, ln in name_rows}
    floor_map = await _resolve_rooms_to_floors(db, building_id, set(per_room_vals.keys()))

    readings = [
        {
            "locationId": rid,
            "name": names.get(rid, rid),
            "value": round(sum(vals) / len(vals), 2),
            "unit": per_room_unit[rid],
            "recordedAt": per_room_latest[rid].isoformat(),
            "floor": floor_map.get(rid, {}).get("name"),
            "floorCode": floor_map.get(rid, {}).get("code"),
        }
        for rid, vals in per_room_vals.items()
    ]

    if floor is not None and str(floor).strip():
        needle = str(floor).strip().casefold()

        def _on_floor(rd: dict) -> bool:
            return any(
                needle in str(v).casefold()
                for v in (rd.get("floor"), rd.get("floorCode"))
                if v
            )

        readings = [rd for rd in readings if _on_floor(rd)]
        if not readings:
            return {
                "ok": False,
                "reason": f"No live temperature readings for floor matching '{floor}'.",
            }

    readings.sort(key=lambda x: x["value"], reverse=True)
    avg = round(sum(r["value"] for r in readings) / len(readings), 2)
    unit = readings[0]["unit"]
    return {
        "ok": True,
        "averageValue": avg,
        "unit": unit,
        "floorFilter": floor or None,
        "locationCount": len(readings),
        "warmest": readings[0],
        "coolest": readings[-1],
        "readings": readings[:20],
    }


async def _resolve_rooms_to_floors(
    db: AsyncSession, building_id: str, room_ids: set[str],
) -> dict[str, dict]:
    """Map each room id to its nearest floor ancestor {'name', 'code'}.

    Walks the parent chain until a location of type 'floor' is found. Rooms
    with no floor level in their ancestry are simply absent from the result.
    """
    if not room_ids:
        return {}
    rows = (
        await db.execute(
            select(
                Location.id,
                Location.parent_id,
                Location.type,
                Location.name,
                Location.code,
            ).where(Location.building_id == building_id)
        )
    ).all()
    by_id = {r.id: r for r in rows}

    out: dict[str, dict] = {}
    for rid in room_ids:
        cur = by_id.get(rid)
        seen: set[str] = set()
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            if cur.type == "floor":
                out[rid] = {"name": cur.name, "code": cur.code}
                break
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
    return out


# ──────────────────────────────────────────────────────────────────────────
# FM / admin analytics helpers + tools
# ──────────────────────────────────────────────────────────────────────────

# Roles allowed to use the building-wide analytics tools (vote sentiment and
# room temperature rankings). Occupants get only their own data.
_ANALYTICS_ROLES = {
    "admin",
    "building_facility_manager",
    "tenant_facility_manager",
}

# Tools that require an FM / admin role.
_ANALYTICS_TOOLS = {"get_temperature_extremes", "get_comfort_by_room"}

_WINDOW_HOURS = {
    "now": 24,
    "live": 24,
    "day": 24,
    "today": 24,
    "24h": 24,
    "week": 168,
    "7d": 168,
}


def _role_name(role: Any) -> str:
    return role.value if hasattr(role, "value") else str(role)


def _filter_readings_by_floor(readings: list[dict], floor: str | None) -> list[dict]:
    """Restrict a readings list to rooms whose floor name/code matches `floor`."""
    if floor is None or not str(floor).strip():
        return readings
    needle = str(floor).strip().casefold()
    return [
        rd
        for rd in readings
        if any(
            needle in str(v).casefold()
            for v in (
                rd.get("floor"),
                rd.get("floorCode"),
                rd.get("floorLabel"),
            )
            if v
        )
    ]


async def _room_temps_window(
    db: AsyncSession, building_id: str, window: str,
) -> list[dict]:
    """Per-room temperature for a time window.

    window "now"/"live"  -> each room's latest sensor reading (value only).
    window "day"/"week"  -> each room's avg over the window, plus min/max.

    Returns a list of {locationId, name, value, minValue, maxValue, unit,
    recordedAt, floor, floorCode, sampleCount}. Empty if no data.
    """
    from collections import defaultdict
    from ..api.telemetry import _resolve_placements_to_rooms

    win = (window or "now").strip().lower()
    live = win in ("now", "live")
    hours = _WINDOW_HOURS.get(win, 24)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    base_filters = (
        TelemetryReading.building_id == building_id,
        TelemetryReading.metric_type == "temperature",
        TelemetryReading.recorded_at >= cutoff,
        TelemetryReading.recorded_at <= now,
        TelemetryReading.location_id.isnot(None),
        TelemetryReading.quality_flag.in_(["good", "suspect"]),
    )

    # Per-sensor aggregates: for "now" we still need the latest value, so we
    # pull avg+min+max+latest_ts and, for live, the value at latest_ts.
    if live:
        latest_ts_subq = (
            select(
                TelemetryReading.location_id.label("location_id"),
                func.max(TelemetryReading.recorded_at).label("max_ts"),
            )
            .where(*base_filters)
            .group_by(TelemetryReading.location_id)
            .subquery()
        )
        stmt = (
            select(
                TelemetryReading.location_id,
                TelemetryReading.value,
                TelemetryReading.recorded_at,
                TelemetryReading.unit,
            )
            .join(
                latest_ts_subq,
                (TelemetryReading.location_id == latest_ts_subq.c.location_id)
                & (TelemetryReading.recorded_at == latest_ts_subq.c.max_ts),
            )
            .where(
                TelemetryReading.building_id == building_id,
                TelemetryReading.metric_type == "temperature",
            )
        )
        raw = (await db.execute(stmt)).all()
        # one latest reading per sensor
        per_sensor: dict[str, Any] = {}
        for r in raw:
            prev = per_sensor.get(r.location_id)
            if prev is None or r.recorded_at > prev.recorded_at:
                per_sensor[r.location_id] = r
        sensor_rows = [
            (r.location_id, float(r.value), float(r.value), float(r.value),
             r.recorded_at, r.unit or "C")
            for r in per_sensor.values()
        ]
    else:
        stmt = (
            select(
                TelemetryReading.location_id,
                func.avg(TelemetryReading.value).label("avg_val"),
                func.min(TelemetryReading.value).label("min_val"),
                func.max(TelemetryReading.value).label("max_val"),
                func.max(TelemetryReading.recorded_at).label("latest_ts"),
                func.min(TelemetryReading.unit).label("unit"),
            )
            .where(*base_filters)
            .group_by(TelemetryReading.location_id)
        )
        rows = (await db.execute(stmt)).all()
        sensor_rows = [
            (r.location_id, float(r.avg_val), float(r.min_val), float(r.max_val),
             r.latest_ts, r.unit or "C")
            for r in rows
        ]

    if not sensor_rows:
        return []

    loc_ids = {sr[0] for sr in sensor_rows}
    room_map = await _resolve_placements_to_rooms(db, loc_ids)

    per_room_vals: dict[str, list[float]] = defaultdict(list)
    per_room_min: dict[str, float] = {}
    per_room_max: dict[str, float] = {}
    per_room_latest: dict[str, datetime] = {}
    per_room_unit: dict[str, str] = {}
    per_room_count: dict[str, int] = defaultdict(int)
    for loc_id, avg_v, min_v, max_v, ts, unit in sensor_rows:
        rid = room_map.get(loc_id, loc_id)
        per_room_vals[rid].append(avg_v)
        per_room_min[rid] = min_v if rid not in per_room_min else min(per_room_min[rid], min_v)
        per_room_max[rid] = max_v if rid not in per_room_max else max(per_room_max[rid], max_v)
        per_room_count[rid] += 1
        if rid not in per_room_latest or (ts and ts > per_room_latest[rid]):
            per_room_latest[rid] = ts
        per_room_unit[rid] = unit

    name_rows = (
        await db.execute(
            select(Location.id, Location.name).where(Location.id.in_(per_room_vals.keys()))
        )
    ).all()
    names = {lid: ln for lid, ln in name_rows}
    floor_map = await _resolve_rooms_to_floors(db, building_id, set(per_room_vals.keys()))

    return [
        {
            "locationId": rid,
            "name": names.get(rid, rid),
            "value": round(sum(vals) / len(vals), 2),
            "minValue": round(per_room_min[rid], 2),
            "maxValue": round(per_room_max[rid], 2),
            "unit": per_room_unit[rid],
            "recordedAt": per_room_latest[rid].isoformat() if per_room_latest[rid] else None,
            "floor": floor_map.get(rid, {}).get("name"),
            "floorCode": floor_map.get(rid, {}).get("code"),
            "sampleCount": per_room_count[rid],
        }
        for rid, vals in per_room_vals.items()
    ]


async def tool_get_temperature_extremes(
    db: AsyncSession,
    building_id: str,
    window: str = "now",
    floor: str | None = None,
    limit: int = 5,
    **_: Any,
) -> dict:
    """Rank rooms by temperature: hottest and coldest, over a time window.

    window: "now" (live latest per room), "day" (last 24h average), or "week"
    (last 7 days average). For day/week each room also carries min/max. Pass
    `floor` to restrict to a floor. FM / admin tool.
    """
    win = (window or "now").strip().lower()
    if win not in _WINDOW_HOURS:
        win = "now"
    limit = max(1, min(int(limit or 5), 20))

    readings = await _room_temps_window(db, building_id, win)
    readings = _filter_readings_by_floor(readings, floor)
    if not readings:
        return {
            "ok": False,
            "reason": f"No temperature readings for window '{win}'"
            + (f" on floor matching '{floor}'." if floor else "."),
        }

    hottest = sorted(readings, key=lambda x: x["value"], reverse=True)[:limit]
    coldest = sorted(readings, key=lambda x: x["value"])[:limit]
    avg = round(sum(r["value"] for r in readings) / len(readings), 2)
    return {
        "ok": True,
        "window": win,
        "unit": readings[0]["unit"],
        "floorFilter": floor or None,
        "averageValue": avg,
        "roomCount": len(readings),
        "hottest": hottest,
        "coldest": coldest,
    }


async def tool_get_comfort_by_room(
    db: AsyncSession,
    building_id: str,
    days: int = 7,
    floor: str | None = None,
    **_: Any,
) -> dict:
    """Aggregate occupant comfort votes per room to find the most uncomfortable.

    Thermal comfort is the centred ASHRAE scale -3 (cold) .. 0 (neutral) ..
    +3 (hot); discomfort is the mean absolute distance from 0. Returns rooms
    ranked by discomfort, plus the warmest- and coolest-reported rooms. Pass
    `floor` to restrict to a floor. FM / admin tool.
    """
    from collections import defaultdict

    days = max(1, min(int(days or 7), 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        await db.execute(
            select(Vote)
            .where(Vote.building_id == building_id, Vote.created_at >= cutoff)
            .order_by(Vote.created_at.desc())
            .limit(10000)
        )
    ).scalars().all()

    agg: dict[str, dict] = defaultdict(
        lambda: {"thermals": [], "floor": None, "floorLabel": None,
                 "stuffy": 0, "airN": 0}
    )
    for v in rows:
        p = v.payload or {}
        zone = p.get("zone") or p.get("room") or p.get("room_label")
        tc = p.get("thermal_comfort")
        if not zone or tc is None:
            continue
        try:
            tc = float(tc)
        except (TypeError, ValueError):
            continue
        a = agg[str(zone)]
        a["thermals"].append(tc)
        if a["floor"] is None and (p.get("floor") or p.get("floor_label")):
            a["floor"] = p.get("floor")
            a["floorLabel"] = p.get("floor_label")
        air = p.get("air")
        if air is not None:
            a["airN"] += 1
            if str(air).lower() == "stuffy":
                a["stuffy"] += 1

    if not agg:
        return {
            "ok": False,
            "reason": f"No occupant comfort votes in the last {days} days.",
        }

    rooms: list[dict] = []
    total_votes = 0
    for zone, a in agg.items():
        ts = a["thermals"]
        n = len(ts)
        if n == 0:
            continue
        total_votes += n
        mean = sum(ts) / n
        discomfort = sum(abs(x) for x in ts) / n
        rooms.append(
            {
                "room": zone,
                "votes": n,
                "meanThermal": round(mean, 2),
                "discomfort": round(discomfort, 2),
                "hotShare": round(sum(1 for x in ts if x >= 1) / n, 2),
                "coldShare": round(sum(1 for x in ts if x <= -1) / n, 2),
                "stuffyShare": round(a["stuffy"] / a["airN"], 2) if a["airN"] else None,
                "floor": a["floor"],
                "floorLabel": a["floorLabel"],
            }
        )

    rooms = _filter_readings_by_floor(rooms, floor)
    if not rooms:
        return {
            "ok": False,
            "reason": f"No comfort votes for floor matching '{floor}'."
            if floor else f"No comfort votes in the last {days} days.",
        }

    most_uncomfortable = sorted(rooms, key=lambda r: r["discomfort"], reverse=True)[:10]
    warmest_reported = sorted(
        (r for r in rooms if r["meanThermal"] > 0),
        key=lambda r: r["meanThermal"], reverse=True,
    )[:5]
    coolest_reported = sorted(
        (r for r in rooms if r["meanThermal"] < 0),
        key=lambda r: r["meanThermal"],
    )[:5]

    return {
        "ok": True,
        "days": days,
        "floorFilter": floor or None,
        "totalVotes": total_votes,
        "roomCount": len(rooms),
        "mostUncomfortable": most_uncomfortable,
        "warmestReported": warmest_reported,
        "coolestReported": coolest_reported,
    }


async def tool_get_temperature_trend(
    db: AsyncSession, building_id: str, hours: int = 6, **_: Any,
) -> dict:
    """Compute whether the building is heating up, cooling down, or steady."""
    hours = max(1, min(int(hours or 6), 72))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    stmt = (
        select(TelemetryReading.recorded_at, TelemetryReading.value)
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.metric_type == "temperature",
            TelemetryReading.recorded_at >= cutoff,
            TelemetryReading.recorded_at <= now,
        )
        .order_by(TelemetryReading.recorded_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    if len(rows) < 2:
        return {
            "ok": False,
            "reason": f"Not enough temperature data in the last {hours}h to compute a trend.",
        }

    # Average the first and last thirds for a robust start/end estimate.
    n = len(rows)
    third = max(1, n // 3)
    start_vals = [row[1] for row in rows[:third]]
    end_vals = [row[1] for row in rows[-third:]]
    start_avg = sum(start_vals) / len(start_vals)
    end_avg = sum(end_vals) / len(end_vals)
    delta = end_avg - start_avg

    if delta > 0.5:
        direction = "heating_up"
    elif delta < -0.5:
        direction = "cooling_down"
    else:
        direction = "steady"

    return {
        "ok": True,
        "hours": hours,
        "startAvg": round(start_avg, 2),
        "endAvg": round(end_avg, 2),
        "deltaC": round(delta, 2),
        "direction": direction,
        "sampleCount": n,
    }


async def tool_get_recent_complaints(
    db: AsyncSession, building_id: str, days: int = 7, **_: Any,
) -> dict:
    """Complaints raised against the building in the last N days."""
    days = max(1, min(int(days or 7), 60))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    stmt = (
        select(Complaint)
        .where(
            Complaint.building_id == building_id,
            Complaint.created_at >= cutoff,
        )
        .order_by(Complaint.created_at.desc())
        .limit(50)
    )
    rows = (await db.execute(stmt)).scalars().unique().all()

    by_type: dict[str, int] = {}
    items = []
    for c in rows:
        t = c.complaint_type.value if hasattr(c.complaint_type, "value") else str(c.complaint_type)
        by_type[t] = by_type.get(t, 0) + 1
        items.append(
            {
                "id": c.id,
                "type": t,
                "title": c.title,
                "cosignCount": len(c.cosigners),
                "createdAt": c.created_at.isoformat(),
            }
        )
    return {
        "ok": True,
        "days": days,
        "totalCount": len(items),
        "byType": by_type,
        "items": items[:15],
    }


async def tool_get_my_votes(
    db: AsyncSession, user_id: str, building_id: str, days: int = 30, **_: Any,
) -> dict:
    """Current user's own comfort votes for this building, last N days."""
    days = max(1, min(int(days or 30), 180))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    stmt = (
        select(Vote)
        .where(
            Vote.user_id == user_id,
            Vote.building_id == building_id,
            Vote.created_at >= cutoff,
        )
        .order_by(Vote.created_at.desc())
        .limit(50)
    )
    votes = (await db.execute(stmt)).scalars().all()

    items = [
        {
            "voteUuid": v.vote_uuid,
            "createdAt": v.created_at.isoformat(),
            "payload": v.payload,
        }
        for v in votes
    ]
    return {"ok": True, "days": days, "count": len(items), "votes": items}


async def tool_create_complaint(
    db: AsyncSession,
    user: User,
    building_id: str,
    complaint_type: str,
    title: str,
    description: str | None = None,
    **_: Any,
) -> dict:
    """Create a complaint. The persona is responsible for confirming with the
    user before calling this tool; the backend does not re-confirm."""
    try:
        ctype = ComplaintType(complaint_type)
    except ValueError:
        return {
            "ok": False,
            "reason": f"Invalid complaintType '{complaint_type}'. "
            f"Valid: hot, cold, air_quality, cleanliness, other.",
        }

    clean_title = (title or "").strip()[:200]
    if not clean_title:
        return {"ok": False, "reason": "Title is required."}

    complaint = Complaint(
        id=f"cmp-{uuid.uuid4().hex[:8]}",
        building_id=building_id,
        created_by=user.id,
        complaint_type=ctype,
        title=clean_title,
        description=(description or None),
    )
    db.add(complaint)
    await db.flush()
    db.add(
        ComplaintCosign(
            id=f"cs-{uuid.uuid4().hex[:8]}",
            complaint_id=complaint.id,
            user_id=user.id,
        )
    )
    await db.commit()
    return {
        "ok": True,
        "id": complaint.id,
        "type": ctype.value,
        "title": clean_title,
    }


# ──────────────────────────────────────────────────────────────────────────
# Gemini tool declarations
# ──────────────────────────────────────────────────────────────────────────


def build_tool_declarations(role: Any = None) -> types.Tool:
    """Return the Gemini Tool with all function declarations for this role.

    The building-wide analytics tools (temperature rankings, occupant comfort
    by room) are only declared for admins and facility managers. Occupants get
    the base set plus their own personal vote history.
    """
    is_analyst = _role_name(role) in _ANALYTICS_ROLES if role is not None else False

    declarations = [
            types.FunctionDeclaration(
                name="get_current_temperature",
                description=(
                    "Get the building's current (LIVE) temperature: each room's "
                    "most recent sensor reading, a building-wide average of those "
                    "live values, explicit warmest and coolest rooms, plus per-room "
                    "readings sorted hottest→coolest. These match the dashboard's "
                    "live room cards. Use the 'warmest' and 'coolest' fields "
                    "directly — do not infer them from the list. Call this when the "
                    "user asks how the building is feeling, asks about temperature, "
                    "or says 'how are you'. To scope to specific floors, pass the "
                    "'floor' argument; each returned reading also carries its "
                    "'floor' so you can reason about a floor range yourself."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "floor": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "Optional floor name or code substring (e.g. '2', "
                                "'2e', 'Begane grond') to restrict warmest/coolest/"
                                "average to that floor. Omit for the whole building."
                            ),
                        ),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="get_temperature_trend",
                description=(
                    "Compute whether the building has been heating up, cooling "
                    "down, or holding steady over the last N hours. Use together "
                    "with get_current_temperature to describe the building's mood."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "hours": types.Schema(
                            type=types.Type.INTEGER,
                            description="Window length in hours (default 6, max 72).",
                        ),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="get_recent_complaints",
                description=(
                    "Fetch complaints raised against this building in the last N "
                    "days (default 7). Use when the user asks 'how's it going', "
                    "wants to vent, or asks what's been bothering you."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "days": types.Schema(
                            type=types.Type.INTEGER,
                            description="How many days back to look (default 7, max 60).",
                        ),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="get_my_votes",
                description=(
                    "Fetch the CURRENT USER's own recent comfort votes for this "
                    "building. Use when the user asks about their own feedback, "
                    "or when you want to connect their personal comfort history "
                    "to what they are experiencing right now."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "days": types.Schema(
                            type=types.Type.INTEGER,
                            description="How many days back to look (default 30, max 180).",
                        ),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="create_complaint",
                description=(
                    "Create a complaint on behalf of the current user. You MUST "
                    "ONLY call this after the user has explicitly confirmed (e.g. "
                    "replied 'yes', 'please do', 'go ahead') in the immediately "
                    "preceding turn. Never call it on a first mention of "
                    "discomfort — first propose it and ask."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "complaint_type": types.Schema(
                            type=types.Type.STRING,
                            description="One of: hot, cold, air_quality, cleanliness, other.",
                        ),
                        "title": types.Schema(
                            type=types.Type.STRING,
                            description="Short title, max ~80 chars, describing the issue.",
                        ),
                        "description": types.Schema(
                            type=types.Type.STRING,
                            description="Optional longer description.",
                        ),
                    },
                    required=["complaint_type", "title"],
                ),
            ),
    ]

    if is_analyst:
        declarations += [
            types.FunctionDeclaration(
                name="get_temperature_extremes",
                description=(
                    "FM/admin: rank rooms by temperature — the hottest and "
                    "coldest rooms — over a window. window='now' uses each room's "
                    "live reading; 'day' the last 24h average; 'week' the last 7 "
                    "days average (day/week also include each room's min/max). "
                    "Use when a manager asks which rooms are hottest/coldest right "
                    "now, today, or this week. Pass 'floor' to scope to a floor."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "window": types.Schema(
                            type=types.Type.STRING,
                            description="One of: now, day, week. Default 'now'.",
                        ),
                        "floor": types.Schema(
                            type=types.Type.STRING,
                            description="Optional floor name/code substring to scope to.",
                        ),
                        "limit": types.Schema(
                            type=types.Type.INTEGER,
                            description="How many rooms per list (default 5, max 20).",
                        ),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="get_comfort_by_room",
                description=(
                    "FM/admin: aggregate ALL occupants' comfort votes per room "
                    "over the last N days to find which rooms occupants report as "
                    "most uncomfortable. Returns rooms ranked by discomfort (mean "
                    "absolute distance from neutral on the -3..+3 thermal scale), "
                    "plus the warmest- and coolest-reported rooms and a stuffiness "
                    "share. Use when a manager asks which rooms people are "
                    "unhappy/complaining about. Pass 'floor' to scope to a floor."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "days": types.Schema(
                            type=types.Type.INTEGER,
                            description="How many days back to look (default 7, max 90).",
                        ),
                        "floor": types.Schema(
                            type=types.Type.STRING,
                            description="Optional floor name/code substring to scope to.",
                        ),
                    },
                ),
            ),
        ]

    return types.Tool(function_declarations=declarations)


# ──────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────


async def dispatch_tool(
    name: str,
    args: dict[str, Any],
    *,
    db: AsyncSession,
    user: User,
    building_id: str,
) -> dict:
    """Execute a tool by name. Unknown tools return an error dict."""
    args = args or {}
    # Building-wide analytics are FM/admin only — guard even if a model is
    # somehow told about them, so an occupant session can never read them.
    if name in _ANALYTICS_TOOLS and _role_name(user.role) not in _ANALYTICS_ROLES:
        return {
            "ok": False,
            "reason": "This data is only available to facility managers and admins.",
        }
    try:
        if name == "get_current_temperature":
            return await tool_get_current_temperature(
                db, building_id, floor=args.get("floor"),
            )
        if name == "get_temperature_extremes":
            return await tool_get_temperature_extremes(
                db, building_id,
                window=args.get("window", "now"),
                floor=args.get("floor"),
                limit=args.get("limit", 5),
            )
        if name == "get_comfort_by_room":
            return await tool_get_comfort_by_room(
                db, building_id,
                days=args.get("days", 7),
                floor=args.get("floor"),
            )
        if name == "get_temperature_trend":
            return await tool_get_temperature_trend(
                db, building_id, hours=args.get("hours", 6),
            )
        if name == "get_recent_complaints":
            return await tool_get_recent_complaints(
                db, building_id, days=args.get("days", 7),
            )
        if name == "get_my_votes":
            return await tool_get_my_votes(
                db, user.id, building_id, days=args.get("days", 30),
            )
        if name == "create_complaint":
            return await tool_create_complaint(
                db,
                user,
                building_id,
                complaint_type=args.get("complaint_type", ""),
                title=args.get("title", ""),
                description=args.get("description"),
            )
        return {"ok": False, "reason": f"Unknown tool '{name}'."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"Tool '{name}' failed: {exc}"}
