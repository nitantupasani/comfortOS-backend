"""
Delete implausible telemetry rows for a building (e.g. faulty sensors stuck at
160 °C). Range comes from priva_ingestion (PLAUSIBLE_MIN/MAX).

Usage (from backend/):
  python -m scripts.priva_cleanup                 # delete out-of-range rows
  python -m scripts.priva_cleanup --dry-run       # count only
  python -m scripts.priva_cleanup --building bldg-xxxx
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func, delete, or_  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models.telemetry import TelemetryReading as T  # noqa: E402
from app.services.priva_ingestion import (  # noqa: E402
    load_building, PLAUSIBLE_MIN, PLAUSIBLE_MAX,
)


async def main(building_id: str, dry_run: bool) -> None:
    cond = (T.building_id == building_id) & or_(
        T.value < PLAUSIBLE_MIN, T.value > PLAUSIBLE_MAX
    )
    async with async_session_factory() as db:
        n = await db.scalar(select(func.count()).select_from(T).where(cond))
        print(f"Implausible rows (<{PLAUSIBLE_MIN} or >{PLAUSIBLE_MAX} °C) for "
              f"{building_id}: {n}")
        if dry_run:
            print("(dry-run) nothing deleted.")
            return
        await db.execute(delete(T).where(cond))
        await db.commit()
        print(f"Deleted {n} rows.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--building", default=None, help="ComfortOS building id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    bid = args.building or load_building(settings.priva_building_file).get("comfortosBuildingId", "")
    if not bid:
        print("ERROR: no building id (set --building or comfortosBuildingId in building file).")
        sys.exit(1)
    asyncio.run(main(bid, args.dry_run))
