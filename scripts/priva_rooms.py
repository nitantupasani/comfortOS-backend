"""
Create room-level Locations for the Priva building and repoint each sensor's
location_id to its room (building -> floor -> room hierarchy).

For every variable in the building file, ensures a Location(type='room') exists
under the variable's floor, named by its NR label, then writes that room's id
back into the building file as the variable's location_id.

Idempotent: existing rooms (same floor + name) are reused, so re-running won't
duplicate. After this, re-run priva_backfill / start priva_run so readings
attach at room granularity.

Usage (from backend/):
  python -m scripts.priva_rooms --dry-run
  python -m scripts.priva_rooms
"""

import argparse
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models.location import Location  # noqa: E402
from app.services.priva_ingestion import load_building, _resolve_path  # noqa: E402


def _floor_num(name: str):
    if "begane" in name.lower():
        return 0
    m = re.match(r"\s*(\d+)", name or "")
    return int(m.group(1)) if m else None


async def main(dry_run: bool) -> None:
    bf = load_building(settings.priva_building_file)
    bid = bf.get("comfortosBuildingId", "")
    floor_loc = bf.get("floorLocations", {})
    variables = bf.get("variables", {})
    if not (bid and floor_loc and variables):
        print("ERROR: building file needs comfortosBuildingId, floorLocations, variables.")
        sys.exit(1)

    def floc_for(floor_name: str):
        n = _floor_num(floor_name)
        return floor_loc.get(str(n)) or floor_loc.get(n)

    async with async_session_factory() as db:
        res = await db.execute(
            select(Location).where(Location.building_id == bid, Location.type == "room")
        )
        existing = {(l.parent_id, l.name): l.id for l in res.scalars().all()}

        mapping: dict[str, str] = {}
        created = 0
        for vid, info in variables.items():
            room = info.get("room")
            floc = floc_for(info.get("floor", ""))
            if not (room and floc):
                continue
            key = (floc, room)
            rid = existing.get(key)
            if rid is None:
                loc = Location(
                    building_id=bid, parent_id=floc, type="room",
                    name=room, code=room,
                    external_refs={
                        "priva_varid": vid,
                        "priva_target": info.get("target"),
                        "priva_section": info.get("section"),
                    },
                )
                if not dry_run:
                    db.add(loc)
                    await db.flush()
                    rid = loc.id
                else:
                    rid = "(new)"
                existing[key] = rid
                created += 1
            mapping[vid] = rid

        if not dry_run:
            await db.commit()
        print(f"Rooms: {len(mapping)} sensors -> rooms, {created} new room locations "
              f"({'dry-run' if dry_run else 'created'}).")

    if dry_run:
        return

    # Repoint each variable's location_id to its room location and save the file.
    for vid, info in variables.items():
        if vid in mapping:
            info["location_id"] = mapping[vid]
    bf["variables"] = variables
    out = _resolve_path(settings.priva_building_file)
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(bf, indent=2, ensure_ascii=False))
    print(f"Updated {out} — location_id now points at room locations.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.dry_run))
