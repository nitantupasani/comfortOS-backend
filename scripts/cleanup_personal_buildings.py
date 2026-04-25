"""List and optionally delete personal buildings directly via the DB.

Use when the in-app delete is failing (e.g. 404 from a stale frontend
bundle) and you need to remove a personal-building row plus all its
FK dependents without going through the API.

Usage from the backend repo root:

    # Just list:
    python -m scripts.cleanup_personal_buildings

    # Delete a specific building by id:
    python -m scripts.cleanup_personal_buildings --delete bldg-abcd1234

    # Delete every personal building belonging to a user:
    python -m scripts.cleanup_personal_buildings --user usr-xxxx --delete-all

Reads DATABASE_URL from app.config.settings, so on the production
server it operates against the production database.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.building import Building


_FK_TABLES: tuple[str, ...] = (
    "user_building_access",
    "building_configs",
    "building_tenants",
    "building_connectors",
    "building_telemetry_config",
    "presence_events",
    "beacons",
    "sensors",
    "telemetry_readings",
    "telemetry_endpoints",
    "votes",
    "complaints",
    "fm_role_requests",
    "chat_sessions",
    "zones",
    "locations",
)


def _is_personal(b: Building) -> bool:
    meta = b.metadata_ if isinstance(b.metadata_, dict) else {}
    return bool(meta.get("isPersonal"))


async def _load_personal(db: AsyncSession, user_id: str | None) -> list[Building]:
    rows = (await db.execute(select(Building))).scalars().all()
    out = [b for b in rows if _is_personal(b)]
    if user_id:
        out = [
            b for b in out
            if isinstance(b.metadata_, dict)
            and b.metadata_.get("createdByUserId") == user_id
        ]
    return out


async def _delete_building(db: AsyncSession, building: Building) -> None:
    for table in _FK_TABLES:
        await db.execute(
            text(f"DELETE FROM {table} WHERE building_id = :bid"),
            {"bid": building.id},
        )
    await db.delete(building)


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--user", help="Filter to personal buildings created by this user id")
    p.add_argument("--delete", help="Delete the personal building with this id")
    p.add_argument(
        "--delete-all",
        action="store_true",
        help="Delete every personal building matching the filter (use with --user)",
    )
    args = p.parse_args()

    async with async_session_factory() as db:
        personal = await _load_personal(db, args.user)

        print(f"Found {len(personal)} personal building(s):")
        for b in personal:
            meta = b.metadata_ or {}
            owner = meta.get("createdByUserId", "?")
            floor = meta.get("floor")
            zone = meta.get("zone")
            extras = ", ".join(
                x for x in [f"floor={floor}" if floor else None, f"zone={zone}" if zone else None] if x
            ) or "—"
            print(f"  {b.id}  name={b.name!r}  owner={owner}  {extras}")

        targets: list[Building] = []
        if args.delete:
            targets = [b for b in personal if b.id == args.delete]
            if not targets:
                print(f"\nNo personal building with id {args.delete!r}")
                return 1
        elif args.delete_all:
            targets = personal

        if not targets:
            return 0

        print(f"\nDeleting {len(targets)} building(s)…")
        for b in targets:
            await _delete_building(db, b)
            print(f"  removed {b.id} ({b.name})")
        await db.commit()
        print("Done.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
