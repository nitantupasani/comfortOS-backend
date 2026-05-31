"""Seed comfort votes that track the building's real temperature data.

For every room we have temperature telemetry for, this samples readings over
their full time span and emits comfort votes whose thermal sensation matches
the measured temperature: a 24 °C room votes "slightly warm", a 21 °C room
votes "neutral", an 18 °C room votes "cool" — never the opposite. Each vote is
timestamped at the reading it was derived from, so the comfort history lines up
with the temperature history.

Thermal scale: centred ASHRAE -3 (cold) .. 0 (neutral) .. +3 (hot), matching
``GET /buildings/{id}/comfort`` (``payload.thermal_comfort``) and the web
VoteFormRenderer.

DB mode (default) writes straight into the ``votes`` table:

    export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db"
    python -m scripts.seed_temp_correlated_votes --building bldg-8f2fd3cf

Votes are idempotent: the vote_uuid is a uuid5 of (building, room, timestamp),
so re-running tops up missing rows without creating duplicates.
"""

import argparse
import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timezone

# Stable namespace so re-runs produce the same vote_uuid per (room, timestamp).
_NS = uuid.UUID("11111111-2222-3333-4444-555555555555")

# ASHRAE neutral temperature and degrees per scale step. 22 °C → 0 (neutral),
# ~1.6 °C moves the sensation by one point.
NEUTRAL_C = 22.0
DEG_PER_STEP = 1.6


def temp_to_sensation(temp_c: float, jitter: float) -> int:
    """Map a temperature to a centred -3..+3 thermal sensation vote.

    `jitter` (std-dev in scale points) adds mild per-occupant variation so the
    cluster is not perfectly deterministic, while staying correlated with temp.
    """
    raw = (temp_c - NEUTRAL_C) / DEG_PER_STEP
    if jitter:
        raw += random.gauss(0.0, jitter)
    return max(-3, min(3, int(round(raw))))


def _vote_uuid(building_id: str, room: str, ts: datetime) -> str:
    return str(uuid.uuid5(_NS, f"{building_id}|{room}|{ts.isoformat()}"))


async def _run_db(args: argparse.Namespace) -> None:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.models.telemetry import TelemetryReading
    from app.models.vote import Vote, VoteStatus

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(2)

    engine = create_async_engine(db_url)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    interval = args.interval_minutes * 60.0

    async with Session() as session:
        # Pull every plausible temperature reading for the building, ordered so
        # we can walk each room's series in time.
        stmt = (
            select(
                TelemetryReading.location_id,
                TelemetryReading.floor,
                TelemetryReading.zone,
                TelemetryReading.value,
                TelemetryReading.recorded_at,
            )
            .where(
                TelemetryReading.building_id == args.building,
                TelemetryReading.metric_type == "temperature",
                TelemetryReading.value != 0,
            )
            .order_by(TelemetryReading.zone, TelemetryReading.recorded_at)
        )
        rows = (await session.execute(stmt)).all()

        if not rows:
            print(f"No temperature readings for {args.building}; nothing to seed.")
            await engine.dispose()
            return

        # Build vote candidates: one per room per sampling interval.
        candidates: list[dict] = []
        per_room_count: dict[str, int] = {}
        last_emit: dict[str, datetime] = {}

        for location_id, floor, zone, value, recorded_at in rows:
            room = zone or location_id or "_unknown"
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)

            prev = last_emit.get(room)
            if prev is not None and (recorded_at - prev).total_seconds() < interval:
                continue
            if per_room_count.get(room, 0) >= args.max_per_room:
                continue
            if random.random() > args.rate:
                last_emit[room] = recorded_at
                continue

            last_emit[room] = recorded_at
            per_room_count[room] = per_room_count.get(room, 0) + 1

            thermal = temp_to_sensation(float(value), args.jitter)
            floor_s = str(floor or "_unknown")
            payload = {
                "floor": floor_s,
                "floor_label": floor_s,
                "room": room,
                "room_label": room,
                "zone": room,
                "thermal_comfort": thermal,
                "source": "seed_temp_correlated",
            }
            candidates.append(
                {
                    "vote_uuid": _vote_uuid(args.building, room, recorded_at),
                    "building_id": args.building,
                    "user_id": args.user,
                    "payload": payload,
                    "schema_version": 2,
                    "status": VoteStatus.confirmed,
                    "created_at": recorded_at,
                }
            )

        if args.max and len(candidates) > args.max:
            random.shuffle(candidates)
            candidates = candidates[: args.max]

        if args.dry_run:
            _print_summary(candidates)
            print(f"[dry-run] would insert {len(candidates)} votes "
                  f"across {len(per_room_count)} rooms")
            await engine.dispose()
            return

        # Idempotent bulk insert — skip rows whose vote_uuid already exists.
        inserted = 0
        CHUNK = 500
        for i in range(0, len(candidates), CHUNK):
            chunk = candidates[i : i + CHUNK]
            stmt = pg_insert(Vote).values(chunk).on_conflict_do_nothing(
                index_elements=["vote_uuid"]
            )
            result = await session.execute(stmt)
            inserted += result.rowcount or 0
        await session.commit()

    await engine.dispose()
    _print_summary(candidates)
    print(f"done: inserted {inserted} new votes "
          f"({len(candidates)} candidates) into {args.building}")


def _print_summary(candidates: list[dict]) -> None:
    if not candidates:
        return
    dist: dict[int, int] = {}
    for c in candidates:
        t = c["payload"]["thermal_comfort"]
        dist[t] = dist.get(t, 0) + 1
    span_lo = min(c["created_at"] for c in candidates)
    span_hi = max(c["created_at"] for c in candidates)
    print(f"thermal_comfort distribution: "
          f"{{ {', '.join(f'{k:+d}: {dist[k]}' for k in sorted(dist))} }}")
    print(f"time span: {span_lo.isoformat()} -> {span_hi.isoformat()}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--building", default="bldg-8f2fd3cf", help="Building id")
    p.add_argument("--interval-minutes", type=int, default=120,
                   help="Min spacing between votes per room (default 120)")
    p.add_argument("--rate", type=float, default=0.6,
                   help="Probability a sampled reading becomes a vote (0..1)")
    p.add_argument("--jitter", type=float, default=0.4,
                   help="Std-dev of thermal-sensation noise in scale points")
    p.add_argument("--max-per-room", type=int, default=60,
                   help="Cap votes per room")
    p.add_argument("--max", type=int, default=8000,
                   help="Global cap on total votes (0 = unlimited)")
    p.add_argument("--user", default=None, help="user_id to stamp (default anonymous/null)")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be inserted without writing")
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    asyncio.run(_run_db(args))


if __name__ == "__main__":
    main()
