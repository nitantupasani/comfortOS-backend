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
    db: AsyncSession, building_id: str, **_: Any,
) -> dict:
    """Latest temperature readings for the building, plus a building-wide average.

    Matches the dashboard /room-summary endpoint: filters out bad-quality and
    null-location rows, averages sensors within each room, and collapses
    placement-level rows into their parent room.
    """
    from collections import defaultdict
    from ..api.telemetry import _resolve_placements_to_rooms

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    stmt = (
        select(
            TelemetryReading.location_id,
            func.avg(TelemetryReading.value).label("avg_val"),
            func.max(TelemetryReading.recorded_at).label("latest_ts"),
            func.min(TelemetryReading.unit).label("unit"),
        )
        .where(
            TelemetryReading.building_id == building_id,
            TelemetryReading.metric_type == "temperature",
            TelemetryReading.recorded_at >= cutoff,
            TelemetryReading.location_id.isnot(None),
            TelemetryReading.quality_flag.in_(["good", "suspect"]),
        )
        .group_by(TelemetryReading.location_id)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"ok": False, "reason": "No temperature readings in the last 24 hours."}

    loc_ids = {r.location_id for r in rows}
    room_map = await _resolve_placements_to_rooms(db, loc_ids)

    per_room_vals: dict[str, list[float]] = defaultdict(list)
    per_room_latest: dict[str, datetime] = {}
    per_room_unit: dict[str, str] = {}
    for r in rows:
        rid = room_map.get(r.location_id, r.location_id)
        per_room_vals[rid].append(float(r.avg_val))
        if rid not in per_room_latest or r.latest_ts > per_room_latest[rid]:
            per_room_latest[rid] = r.latest_ts
        per_room_unit[rid] = r.unit or "C"

    name_rows = (
        await db.execute(
            select(Location.id, Location.name).where(Location.id.in_(per_room_vals.keys()))
        )
    ).all()
    names = {lid: ln for lid, ln in name_rows}

    readings = [
        {
            "locationId": rid,
            "name": names.get(rid, rid),
            "value": round(sum(vals) / len(vals), 2),
            "unit": per_room_unit[rid],
            "recordedAt": per_room_latest[rid].isoformat(),
        }
        for rid, vals in per_room_vals.items()
    ]
    readings.sort(key=lambda x: x["value"], reverse=True)
    avg = round(sum(r["value"] for r in readings) / len(readings), 2)
    unit = readings[0]["unit"]
    return {
        "ok": True,
        "averageValue": avg,
        "unit": unit,
        "locationCount": len(readings),
        "warmest": readings[0],
        "coolest": readings[-1],
        "readings": readings[:20],
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


def build_tool_declarations() -> types.Tool:
    """Return the Gemini Tool containing all function declarations."""
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_current_temperature",
                description=(
                    "Get the building's current temperature: building-wide "
                    "average, explicit warmest and coolest rooms, plus per-room "
                    "readings sorted hottest→coolest. Use the 'warmest' and "
                    "'coolest' fields directly — do not infer them from the list. "
                    "Call this when the user asks how the building is feeling, "
                    "asks about temperature, or says 'how are you'."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={},
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
    )


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
    try:
        if name == "get_current_temperature":
            return await tool_get_current_temperature(db, building_id)
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
