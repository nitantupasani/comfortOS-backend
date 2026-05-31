"""
Standalone Priva SignalR validator -- NO database writes.

Confirms the copied BFF cookie works end-to-end: negotiate -> connect ->
subscribe -> print live telemetryChangedCallback pushes. Use this to:
  * verify the __Host-bff cookie is still valid,
  * watch which variableId reports which value (to fill priva_variables.json),
  * sanity-check the protocol before enabling PRIVA_ENABLED in the app.

Usage (from backend/):
  set PRIVA_BFF_COOKIE=__Host-bff=...        (PowerShell: $env:PRIVA_BFF_COOKIE="...")
  python -m scripts.test_priva               # subscribes to priva_variables.json
  python -m scripts.test_priva --seconds 120 # stop after 2 min

The cookie can be the full Cookie header or just the __Host-bff=... pair.
Site/server/group default to the captured 'Begane grond' values; override via env.
"""

import argparse
import asyncio
import json
import os
import sys

# Allow running as `python scripts/test_priva.py` too
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402  (loads .env — no hardcoded secrets)
from app.services.priva_ingestion import (  # noqa: E402
    RS, negotiate, build_subscribe_frames, load_building,
)
import websockets  # noqa: E402

# Identity comes from the building file; cookie from .env. Nothing hardcoded.
_BUILDING = load_building(settings.priva_building_file)
SITE = _BUILDING.get("siteId", "")
GROUP = (_BUILDING.get("groups") or [""])[0]
SERVERS = _BUILDING.get("servers", {})
VAR_MAP = _BUILDING.get("variables", {})


async def main(seconds: int) -> None:
    cookie = settings.priva_bff_cookie
    if not cookie:
        print("ERROR: set PRIVA_BFF_COOKIE in .env (the __Host-bff=... pair).")
        sys.exit(1)
    if not (SITE and GROUP and SERVERS and VAR_MAP):
        print(f"ERROR: building file incomplete: {settings.priva_building_file}")
        sys.exit(1)

    var_map = VAR_MAP
    frames = build_subscribe_frames(var_map, SITE, GROUP, SERVERS)
    subbed = sum(len(f["arguments"][0]) for f in frames)
    print(f"Loaded {len(var_map)} variables; subscribing {subbed} across "
          f"{len(frames)} controller(s) from {settings.priva_building_file}")

    ws_url = await negotiate(cookie)
    print("Negotiate OK. Connecting...")

    async with websockets.connect(ws_url, max_size=None, ping_interval=None) as ws:
        await ws.send(json.dumps({"protocol": "json", "version": 1}) + RS)
        await ws.recv()
        for frame in frames:
            await ws.send(json.dumps(frame) + RS)
        print(f"Subscribed. Streaming for {seconds}s (Ctrl+C to stop)...\n")

        async def _ping():
            while True:
                await asyncio.sleep(15)
                await ws.send(json.dumps({"type": 6}) + RS)

        ping = asyncio.create_task(_ping())
        seen: dict[str, float] = {}
        try:
            async with asyncio.timeout(seconds):
                async for raw in ws:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", "ignore")
                    for part in raw.split(RS):
                        if not part:
                            continue
                        msg = json.loads(part)
                        if msg.get("target") == "telemetryChangedCallback":
                            for item in msg["arguments"][0]:
                                ref = item.get("variableNodeReference", {})
                                vid = ref.get("variableId")
                                if vid:
                                    seen[vid] = float(item.get("value", 0))
        except (asyncio.TimeoutError, KeyboardInterrupt):
            pass
        finally:
            ping.cancel()

    # Per-floor tally: how many subscribed vars actually streamed a value.
    from collections import defaultdict
    by_floor: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for vid, info in var_map.items():
        floor = info.get("floor", "?")
        by_floor[floor][1] += 1
        if vid in seen:
            by_floor[floor][0] += 1
    print(f"\nReceived values for {len(seen)}/{len(var_map)} variables:")
    for floor in sorted(by_floor):
        got, tot = by_floor[floor]
        print(f"  {floor:<16} {got}/{tot}")
    print("Done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=90)
    args = ap.parse_args()
    asyncio.run(main(args.seconds))
