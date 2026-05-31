"""
Priva history backfill — pull ~1 month of temperature history and store it
downsampled to a 15-minute grid.

Uses the Operator history endpoint (same BFF cookie):

  POST /operator/api/history/variables/{siteId}
  { "deviceGroupId": "p57560",
    "variables": [ {"deviceGroupId","deviceId"(=server),"variableId"}, ... ],
    "startTime": "YYYY-MM-DD HH:MM:SS",   # UTC
    "endTime":   "YYYY-MM-DD HH:MM:SS" }  # UTC

Response per variable: { variableId, deviceId, timezoneOffset(minutes),
dataValues:[{Timestamp(LOCAL), Value}] }. Raw cadence is ~8 min.

We request UTC, convert each LOCAL Timestamp back to UTC (minus timezoneOffset),
floor to a 15-minute grid (last sample wins per slot), and store one
TelemetryReading per slot with connector_id="priva-signalr-backfill".

Usage (from backend/, cookie in .env, identity+vars from the building file):
  python -m scripts.priva_backfill                 # last 30 days
  python -m scripts.priva_backfill --days 31
  python -m scripts.priva_backfill --dry-run       # fetch+count, no DB write
  python -m scripts.priva_backfill --keep          # don't delete prior backfill rows

Requires the building file to have a valid comfortosBuildingId.
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models.telemetry import TelemetryReading  # noqa: E402
from app.services.priva_ingestion import load_building, is_plausible  # noqa: E402

HIST_URL = "https://operator.priva.com/operator/api/history/variables/{site}"


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _windows(start: datetime, end: datetime, window_days: int):
    """Yield (win_start, win_end) spans. The history endpoint caps each response
    at ~555 points, so it auto-coarsens long ranges; <=3 days keeps the full
    8-minute resolution."""
    cur = start
    step = timedelta(days=window_days)
    while cur < end:
        nxt = min(cur + step, end)
        yield cur, nxt
        cur = nxt


def _downsample_15(data_values: list[dict], tz_offset_min: int) -> dict[datetime, float]:
    """LOCAL Timestamps -> UTC, floored to 15-min slots. Last sample wins."""
    grid: dict[datetime, float] = {}
    for p in data_values:
        ts, val = p.get("Timestamp"), p.get("Value")
        if ts is None or val is None:
            continue
        if not is_plausible(float(val)):
            continue  # drop faulty sensor readings (e.g. stuck 160 °C)
        local = datetime.fromisoformat(ts)
        utc = local - timedelta(minutes=tz_offset_min)
        slot = utc.replace(
            minute=(utc.minute // 15) * 15, second=0, microsecond=0,
            tzinfo=timezone.utc,
        )
        grid[slot] = float(val)  # dataValues are chronological -> last wins
    return grid


async def _fetch(client: httpx.AsyncClient, site: str, group: str,
                 items: list[tuple[str, dict]], start: str, end: str) -> list[dict]:
    body = {
        "deviceGroupId": group,
        "variables": [
            {"deviceGroupId": group, "deviceId": info.get("server"), "variableId": vid}
            for vid, info in items
        ],
        "startTime": start,
        "endTime": end,
    }
    r = await client.post(HIST_URL.format(site=site), json=body)
    r.raise_for_status()
    return r.json()


async def main(days: int, chunk: int, window_days: int, dry_run: bool, keep: bool) -> None:
    cookie = settings.priva_bff_cookie
    building = load_building(settings.priva_building_file)
    var_map = building.get("variables", {})
    site = building.get("siteId", "")
    group = (building.get("groups") or [""])[0]
    building_id = building.get("comfortosBuildingId", "")

    if not (cookie and site and group and var_map):
        print("ERROR: need PRIVA_BFF_COOKIE in .env and siteId/groups/variables in building file.")
        sys.exit(1)
    if not building_id and not dry_run:
        print("ERROR: building file has no comfortosBuildingId — set it (or use --dry-run).")
        sys.exit(1)

    end = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    start = end - timedelta(days=days)
    wins = list(_windows(start, end, window_days))
    print(f"Backfill {len(var_map)} vars, {start} .. {end} UTC ({days}d), "
          f"{len(wins)} x {window_days}d windows -> 15-min grid")

    headers = {
        "Cookie": cookie, "x-csrf": "1",
        "Content-Type": "application/json", "Accept": "application/json",
        "Origin": "https://operator.priva.com",
        "Referer": "https://operator.priva.com/",
    }
    items = list(var_map.items())

    # Clear prior backfill rows for a clean idempotent re-run.
    if not dry_run and not keep:
        async with async_session_factory() as db:
            await db.execute(delete(TelemetryReading).where(
                TelemetryReading.building_id == building_id,
                TelemetryReading.connector_id == "priva-signalr-backfill",
            ))
            await db.commit()
        print("Cleared previous backfill rows.")

    n_chunks = (len(items) + chunk - 1) // chunk
    total_rows = 0
    async with httpx.AsyncClient(headers=headers, timeout=180) as client:
        for ci, group_items in enumerate(_chunks(items, chunk), 1):
            # Merge all windows into one slot->value grid per variable.
            grids: dict[str, dict[datetime, float]] = defaultdict(dict)
            for win_start, win_end in wins:
                s_str = win_start.strftime("%Y-%m-%d %H:%M:%S")
                e_str = win_end.strftime("%Y-%m-%d %H:%M:%S")
                try:
                    series = await _fetch(client, site, group, group_items, s_str, e_str)
                except Exception as exc:
                    print(f"  ! chunk {ci} {s_str}: {type(exc).__name__}: {exc}")
                    continue
                for s in series:
                    vid = s.get("variableId")
                    grids[vid].update(
                        _downsample_15(s.get("dataValues", []), s.get("timezoneOffset", 0))
                    )

            rows: list[TelemetryReading] = []
            for vid, grid in grids.items():
                info = var_map.get(vid, {})
                for slot, val in grid.items():
                    rows.append(TelemetryReading(
                        building_id=building_id,
                        location_id=info.get("location_id"),
                        metric_type=info.get("metric", "temperature"),
                        value=val,
                        unit=info.get("unit", "C"),
                        recorded_at=slot,
                        source_level="sensor",
                        connector_id="priva-signalr-backfill",
                        floor=info.get("floor"),
                        zone=info.get("room"),
                        metadata_={"variableId": vid, "source": "history"},
                    ))

            total_rows += len(rows)
            print(f"  chunk {ci}/{n_chunks}: {len(grids)} vars -> {len(rows)} rows (15-min)")

            if not dry_run and rows:
                async with async_session_factory() as db:
                    for batch in _chunks(rows, 5000):
                        db.add_all(batch)
                        await db.flush()
                    await db.commit()

    print(f"\n{'(dry-run) would store' if dry_run else 'Stored'} {total_rows} readings "
          f"(connector_id='priva-signalr-backfill').")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--chunk", type=int, default=15, help="variables per history request")
    ap.add_argument("--window-days", type=int, default=3,
                    help="time window per request (<=3 keeps full 8-min resolution)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="don't delete prior backfill rows")
    args = ap.parse_args()
    asyncio.run(main(args.days, args.chunk, args.window_days, args.dry_run, args.keep))
