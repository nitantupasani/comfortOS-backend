"""Seed comfort votes for the Vertigo demo building so the relatedness-first
Building Comfort screen has realistic data to render.

Two modes:

1. **API mode (default).** Posts votes through ``POST /votes`` against the
   live backend. Requires a valid Firebase ID token belonging to a user
   that can vote on the target building.

       export COMFORTOS_TOKEN="<firebase-id-token>"
       export COMFORTOS_API="https://api.scientify.in"
       python scripts/seed_vertigo_votes.py --building bldg-vertigo --votes 40

   The daily-vote rate limiter applies, so the script throttles itself
   and uses ``schemaVersion=2`` to mark these as bulk-seeded.

2. **DB mode.** Writes rows directly into the ``votes`` table using
   ``DATABASE_URL``. Bypasses the rate limiter; useful for local dev or
   when you have psql access but no Firebase token.

       export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db"
       python scripts/seed_vertigo_votes.py --mode db --building bldg-vertigo --votes 40

The vote payload includes ``floor``, ``floor_label``, ``room``,
``room_label``, ``thermal_comfort`` (centred -3..+3 ASHRAE scale),
``air`` and ``noise`` axes. The matching backend ``GET /buildings/{id}/comfort``
handler groups by ``(floor, room)`` and returns ``locations[]`` for the
frontend to plot.
"""

import argparse
import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

# ── Floor/room layout for the Vertigo demo ──────────────────────────────────
FLOORS = [
    ("3", "Floor 3", [
        ("3-E07", "Room 3.E.07"),
        ("3-W12", "Room 3.W.12"),
        ("3-E04", "Room 3.E.04"),
    ]),
    ("4", "Floor 4", [
        ("4-E11", "Room 4.E.11"),
        ("4-W08", "Room 4.W.08"),
    ]),
    ("5", "Floor 5", [
        ("5-W02", "Room 5.W.02"),
        ("5-E03", "Room 5.E.03"),
    ]),
    ("2", "Floor 2", [
        ("2-E04", "Room 2.E.04"),
    ]),
]

# Bias each floor toward a different thermal mood so the cluster looks
# heterogeneous rather than uniform: floor 3 mostly comfortable, floor 4 a bit
# warm, floor 5 a bit cool, floor 2 mixed.
FLOOR_BIAS = {
    "3": [-1, 0, 0, 0, 0, 1],
    "4": [0, 1, 1, 2, 1, 0],
    "5": [0, -1, -1, -2, -1, 0],
    "2": [-2, -1, 0, 1, 2, 0],
}

AIR_OPTIONS = ["fresh", "acceptable", "stuffy"]
NOISE_OPTIONS = [-2, -1, 0, 1, 2]


def _make_payload(floor: str, floor_label: str, room: str, room_label: str) -> dict:
    thermal = random.choice(FLOOR_BIAS.get(floor, [-1, 0, 0, 1]))
    return {
        "floor": floor,
        "floor_label": floor_label,
        "room": room,
        "room_label": room_label,
        "zone": room,
        "thermal_comfort": thermal,
        "air": random.choice(AIR_OPTIONS),
        "noise": random.choice(NOISE_OPTIONS),
    }


def _make_votes(building_id: str, n: int, user_id: str) -> list[dict]:
    """Return n vote dicts in the API submit shape, spread across floors."""
    out: list[dict] = []
    locations = [
        (f, fl, r, rl) for f, fl, rooms in FLOORS for r, rl in rooms
    ]
    now = datetime.now(timezone.utc)
    for i in range(n):
        floor, floor_label, room, room_label = random.choice(locations)
        payload = _make_payload(floor, floor_label, room, room_label)
        # Spread timestamps across the last 90 minutes for a "live" feel.
        offset_minutes = random.randint(0, 90)
        created_at = (now - timedelta(minutes=offset_minutes)).isoformat()
        out.append(
            {
                "voteUuid": str(uuid.uuid4()),
                "buildingId": building_id,
                "userId": user_id,
                "payload": payload,
                "schemaVersion": 2,
                "createdAt": created_at,
                "status": "confirmed",
            }
        )
    return out


# ─────────────────────────── API MODE ───────────────────────────────────────
def _run_api(building_id: str, n: int, user_id: str, throttle: float) -> None:
    import requests

    api = os.environ.get("COMFORTOS_API", "https://api.scientify.in").rstrip("/")
    token = os.environ.get("COMFORTOS_TOKEN")
    if not token:
        print("ERROR: COMFORTOS_TOKEN is not set", file=sys.stderr)
        sys.exit(2)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    votes = _make_votes(building_id, n, user_id)

    accepted = 0
    duplicates = 0
    errors = 0
    for i, v in enumerate(votes, 1):
        try:
            r = requests.post(f"{api}/votes", json=v, headers=headers, timeout=10)
            if r.status_code == 200:
                body = r.json()
                if body.get("status") == "already_accepted":
                    duplicates += 1
                else:
                    accepted += 1
            elif r.status_code == 429:
                print(f"[{i}/{n}] rate limited; sleeping 60 s")
                import time
                time.sleep(60)
                continue
            else:
                errors += 1
                print(f"[{i}/{n}] {r.status_code} {r.text[:200]}")
        except Exception as e:
            errors += 1
            print(f"[{i}/{n}] error: {e}")
        if throttle:
            import time
            time.sleep(throttle)

    print(f"done: accepted={accepted} duplicates={duplicates} errors={errors}")


# ─────────────────────────── DB MODE ────────────────────────────────────────
async def _run_db(building_id: str, n: int, user_id: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.models.vote import Vote, VoteStatus

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(2)
    engine = create_async_engine(db_url)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    votes = _make_votes(building_id, n, user_id)
    async with Session() as session:
        for v in votes:
            row = Vote(
                vote_uuid=v["voteUuid"],
                building_id=v["buildingId"],
                user_id=v["userId"],
                payload=v["payload"],
                schema_version=v["schemaVersion"],
                status=VoteStatus.confirmed,
                created_at=datetime.fromisoformat(v["createdAt"].replace("Z", "+00:00")),
            )
            session.add(row)
        await session.commit()
    await engine.dispose()
    print(f"done: inserted {n} votes via DB into {building_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--building", default="bldg-vertigo", help="Building id")
    parser.add_argument("--votes", type=int, default=40, help="Number of votes to seed")
    parser.add_argument("--user", default="usr-occupant", help="User id stored on each vote (DB mode)")
    parser.add_argument("--mode", choices=["api", "db"], default="api")
    parser.add_argument("--throttle", type=float, default=0.0, help="Seconds between API posts")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducibility")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    if args.mode == "api":
        _run_api(args.building, args.votes, args.user, args.throttle)
    else:
        asyncio.run(_run_db(args.building, args.votes, args.user))


if __name__ == "__main__":
    main()
