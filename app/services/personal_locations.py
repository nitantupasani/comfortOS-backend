"""Personal-building <-> Location-row sync helpers.

Personal buildings store their structure in two places:
  * ``Building.metadata_`` keyed under ``blocks`` / ``rooms`` (occupant-facing).
  * ``Location`` rows (admin/FM-facing).

These helpers keep them in sync. ``Location`` rows are the canonical
source; ``materialize_personal_locations`` seeds them from metadata for
buildings that pre-date the sync, and ``project_locations_to_metadata``
rebuilds the metadata view from the rows after any mutation.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.building import Building
from ..models.location import Location


def _floor_label(n: int) -> str:
    if n == 0:
        return "Ground floor"
    if n < 0:
        return f"Basement {abs(n)}"
    return f"Floor {n}"


def floor_num_from_location(loc: Location) -> int | None:
    """Recover the integer floor number from a 'floor' Location, or None."""
    code = (loc.code or "").strip()
    if code and code[0] in ("F", "f"):
        try:
            return int(code[1:])
        except ValueError:
            pass
    name = (loc.name or "").strip()
    lower = name.lower()
    if lower in ("ground floor", "ground"):
        return 0
    for prefix, sign in (("floor ", 1), ("basement ", -1), ("level ", 1), ("b", -1)):
        if lower.startswith(prefix):
            tail = lower[len(prefix):].strip()
            try:
                return sign * int(tail)
            except ValueError:
                continue
    try:
        return int(lower)
    except ValueError:
        return None


async def materialize_personal_locations(
    building: Building, db: AsyncSession
) -> bool:
    """Idempotently create Location rows from a personal building's metadata.blocks/rooms. Returns True iff rows were created."""
    meta = building.metadata_ if isinstance(building.metadata_, dict) else {}
    if not meta.get("isPersonal"):
        return False

    existing = await db.execute(
        select(Location.id).where(Location.building_id == building.id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return False

    blocks = meta.get("blocks") or []
    rooms = meta.get("rooms") or []

    root = Location(
        building_id=building.id,
        parent_id=None,
        type="building",
        name=building.name,
        code="ROOT",
    )
    db.add(root)
    await db.flush()

    floor_by_block_and_num: dict[tuple[str, int], str] = {}

    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        block_name = (block.get("name") or "").strip()
        if not block_name:
            continue
        start_floor = block.get("startFloor")
        end_floor = block.get("endFloor")
        if not isinstance(start_floor, int) or not isinstance(end_floor, int):
            continue
        if end_floor < start_floor:
            continue

        block_node = Location(
            building_id=building.id,
            parent_id=root.id,
            type="block_or_wing",
            name=block_name,
            sort_order=idx,
        )
        db.add(block_node)
        await db.flush()

        for fi, fnum in enumerate(range(start_floor, end_floor + 1)):
            floor_node = Location(
                building_id=building.id,
                parent_id=block_node.id,
                type="floor",
                name=_floor_label(fnum),
                code=f"F{fnum}",
                sort_order=fi,
            )
            db.add(floor_node)
            await db.flush()
            floor_by_block_and_num[(block_name, fnum)] = floor_node.id

    room_sort_by_floor: dict[str, int] = {}
    for room in rooms:
        if not isinstance(room, dict):
            continue
        label = (room.get("label") or "").strip()
        if not label:
            continue
        block_name = (room.get("block") or "").strip()
        floor_num = room.get("floor")
        if not isinstance(floor_num, int) or not block_name:
            continue
        floor_id = floor_by_block_and_num.get((block_name, floor_num))
        if floor_id is None:
            continue
        sort_idx = room_sort_by_floor.get(floor_id, 0)
        room_sort_by_floor[floor_id] = sort_idx + 1
        db.add(
            Location(
                building_id=building.id,
                parent_id=floor_id,
                type="room",
                name=label,
                sort_order=sort_idx,
            )
        )

    return True


async def project_locations_to_metadata(
    building: Building, db: AsyncSession
) -> None:
    """Rebuild metadata.blocks/rooms from Location rows for a personal building.

    No-op for non-personal buildings. Floors that can't be mapped back to
    an integer (admin renamed them to e.g. "Mezzanine") are kept as
    Locations but skipped from the metadata projection. Legacy label-only
    rooms (no block/floor) already in metadata are preserved.
    """
    meta = dict(building.metadata_) if isinstance(building.metadata_, dict) else {}
    if not meta.get("isPersonal"):
        return

    result = await db.execute(
        select(Location)
        .where(Location.building_id == building.id)
        .order_by(Location.sort_order, Location.name)
    )
    all_locs = list(result.scalars().all())

    children: dict[str | None, list[Location]] = {}
    for loc in all_locs:
        children.setdefault(loc.parent_id, []).append(loc)

    root = next(
        (l for l in all_locs if l.parent_id is None and l.type == "building"),
        None,
    )

    blocks: list[dict] = []
    rooms: list[dict] = []

    if root is not None:
        for block_loc in children.get(root.id, []):
            if block_loc.type != "block_or_wing":
                continue
            floor_nums: list[int] = []
            for floor_loc in children.get(block_loc.id, []):
                if floor_loc.type != "floor":
                    continue
                fnum = floor_num_from_location(floor_loc)
                if fnum is not None:
                    floor_nums.append(fnum)
                for room_loc in children.get(floor_loc.id, []):
                    if room_loc.type != "room" or fnum is None:
                        continue
                    rooms.append({
                        "block": block_loc.name,
                        "floor": fnum,
                        "label": room_loc.name,
                    })
            if floor_nums:
                blocks.append({
                    "name": block_loc.name,
                    "startFloor": min(floor_nums),
                    "endFloor": max(floor_nums),
                })

    legacy_orphans = [
        r for r in (meta.get("rooms") or [])
        if isinstance(r, dict)
        and not r.get("block")
        and r.get("floor") is None
        and (r.get("label") or "").strip()
    ]
    rooms.extend(legacy_orphans)

    new_meta = {**meta, "blocks": blocks, "rooms": rooms}
    building.metadata_ = new_meta
