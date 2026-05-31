"""Seed comfort votes that loosely track the building's real temperature data.

Goal: a believable, sparse comfort history — about ~30 votes per day spread at
random times across random rooms, with thermal sensation correlated to the
measured temperature but with real spread: mostly neutral / slightly warm /
slightly cool, rarely extreme. Each vote is timestamped at the reading it was
derived from.

Thermal scale: centred ASHRAE -3 (cold) .. 0 (neutral) .. +3 (hot), matching
``GET /buildings/{id}/comfort`` (``payload.thermal_comfort``).

DB mode writes straight into the ``votes`` table:

    export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db"
    # clear any previous seed, then add ~30/day with spread:
    python -m scripts.seed_temp_correlated_votes --purge --per-day 30 --seed 42

Votes are tagged ``payload.source = "seed_temp_correlated"`` so a re-run with
``--purge`` removes exactly the rows this script created. The vote_uuid is a
uuid5 of (building, room, timestamp), so seeding is idempotent.
"""

import argparse
import asyncio
import os
import random
import sys
import uuid
from collections import defaultdict
from datetime import timezone

_NS = uuid.UUID("11111111-2222-3333-4444-555555555555")
SOURCE_TAG = "seed_temp_correlated"


def temp_to_sensation(
    temp_c: float, neutral: float, deg_per_step: float, jitter: float, max_abs: int
) -> int:
    """Map a temperature to a centred thermal sensation, clamped to ±max_abs.

    `neutral` is the temperature treated as 0; `deg_per_step` is how many °C
    moves the sensation by one point (larger = gentler). `jitter` adds gaussian
    spread (in scale points) so a warm room still produces some neutral and
    occasionally slightly-cool votes — believable inter-occupant variation.
    """
    raw = (temp_c - neutral) / deg_per_step + random.gauss(0.0, jitter)
    return max(-max_abs, min(max_abs, int(round(raw))))


def _vote_uuid(building_id: str, room: str, ts_iso: str) -> str:
    return str(uuid.uuid5(_NS, f"{building_id}|{room}|{ts_iso}"))


async def _run_db(args: argparse.Namespace) -> None:
    from sqlalchemy import select, text
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

    async with Session() as session:
        # Optionally clear previous seed rows for this building.
        if args.purge:
            if args.dry_run:
                cnt = (await session.execute(
                    text("SELECT count(*) FROM votes WHERE building_id = :b "
                         "AND payload->>'source' = :s"),
                    {"b": args.building, "s": SOURCE_TAG},
                )).scalar()
                print(f"[dry-run] would purge {cnt} existing seeded votes")
            else:
                res = await session.execute(
                    text("DELETE FROM votes WHERE building_id = :b "
                         "AND payload->>'source' = :s"),
                    {"b": args.building, "s": SOURCE_TAG},
                )
                await session.commit()
                print(f"purged {res.rowcount or 0} existing seeded votes")

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
            .order_by(TelemetryReading.recorded_at)
        )
        rows = (await session.execute(stmt)).all()

        if not rows:
            print(f"No temperature readings for {args.building}; nothing to seed.")
            await engine.dispose()
            return

        # Bucket readings by calendar day so we can target ~per_day votes/day.
        by_day: dict[object, list] = defaultdict(list)
        for location_id, floor, zone, value, recorded_at in rows:
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)
            room = zone or location_id or "_unknown"
            by_day[recorded_at.date()].append(
                (room, str(floor or "_unknown"), float(value), recorded_at)
            )

        # For each day, sample a randomised number of readings (random rooms,
        # random times) and turn each into a vote.
        candidates: list[dict] = []
        seen_keys: set[str] = set()
        for day in sorted(by_day):
            pool = by_day[day]
            target = args.per_day * random.uniform(1 - args.freq_jitter, 1 + args.freq_jitter)
            n = min(len(pool), max(0, int(round(target))))
            for room, floor_s, value, ts in random.sample(pool, n):
                key = _vote_uuid(args.building, room, ts.isoformat())
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                thermal = temp_to_sensation(
                    value, args.neutral, args.deg_per_step, args.jitter, args.max_abs
                )
                candidates.append(
                    {
                        "vote_uuid": key,
                        "building_id": args.building,
                        "user_id": args.user,
                        "payload": {
                            "floor": floor_s,
                            "floor_label": floor_s,
                            "room": room,
                            "room_label": room,
                            "zone": room,
                            "thermal_comfort": thermal,
                            "source": SOURCE_TAG,
                        },
                        "schema_version": 2,
                        "status": VoteStatus.confirmed,
                        "created_at": ts,
                    }
                )

        _print_summary(candidates, len(by_day))

        if args.dry_run:
            print(f"[dry-run] would insert {len(candidates)} votes")
            await engine.dispose()
            return

        inserted = 0
        CHUNK = 500
        for i in range(0, len(candidates), CHUNK):
            chunk = candidates[i : i + CHUNK]
            ins = pg_insert(Vote).values(chunk).on_conflict_do_nothing(
                index_elements=["vote_uuid"]
            )
            res = await session.execute(ins)
            inserted += res.rowcount or 0
        await session.commit()

    await engine.dispose()
    print(f"done: inserted {inserted} new votes "
          f"({len(candidates)} candidates) into {args.building}")


def _print_summary(candidates: list[dict], n_days: int) -> None:
    if not candidates:
        print("no candidates generated")
        return
    dist: dict[int, int] = {}
    for c in candidates:
        t = c["payload"]["thermal_comfort"]
        dist[t] = dist.get(t, 0) + 1
    span_lo = min(c["created_at"] for c in candidates)
    span_hi = max(c["created_at"] for c in candidates)
    avg = len(candidates) / n_days if n_days else 0
    print(f"thermal_comfort distribution: "
          f"{{ {', '.join(f'{k:+d}: {dist[k]}' for k in sorted(dist))} }}")
    print(f"{len(candidates)} votes over {n_days} days (~{avg:.0f}/day)")
    print(f"time span: {span_lo.isoformat()} -> {span_hi.isoformat()}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--building", default="bldg-8f2fd3cf", help="Building id")
    p.add_argument("--per-day", type=int, default=30, help="Target votes per day")
    p.add_argument("--freq-jitter", type=float, default=0.35,
                   help="Random +/- fraction on the per-day count (0..1)")
    p.add_argument("--neutral", type=float, default=23.5,
                   help="Temperature (°C) treated as neutral (0 on the scale)")
    p.add_argument("--deg-per-step", type=float, default=2.4,
                   help="°C per one thermal-sensation step (larger = gentler)")
    p.add_argument("--jitter", type=float, default=0.85,
                   help="Std-dev of per-vote sensation noise in scale points")
    p.add_argument("--max-abs", type=int, default=2,
                   help="Clamp sensation to +/- this (2 = never 'extreme')")
    p.add_argument("--user", default=None, help="user_id to stamp (default null)")
    p.add_argument("--purge", action="store_true",
                   help="Delete this script's previously seeded votes first")
    p.add_argument("--seed", type=int, default=None, help="RNG seed")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would happen without writing")
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    asyncio.run(_run_db(args))


if __name__ == "__main__":
    main()
