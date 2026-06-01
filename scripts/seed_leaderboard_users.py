"""Seed dummy Dutch occupants and attach existing votes to them so the
occupant leaderboard / eco-tree has realistic ranking data.

Targets the Priva demo building **Fluwelen Burgwal 58** (``bldg-8f2fd3cf``),
whose votes are currently anonymous (``user_id IS NULL``, ingested via
``POST /votes/ingest``). This script:

1. Upserts ~10 dummy occupant users with Dutch names (ids ``usr-dummy-<slug>``).
2. Grants each an explicit ``UserBuildingAccess`` to the building.
3. Reassigns the building's existing votes across those users with a Zipf-ish
   weight (a few power-contributors + a long tail) so the leaderboard ranking
   looks natural. Assignment is **deterministic** (hash of ``vote_uuid``), so
   re-running is stable and idempotent. Only ``user_id`` is touched.

Optionally (``--topup N``) it adds N synthesized votes per user spread over the
last 14 days to make voting **streaks** livelier. Default 0 to keep the real
Priva comfort analytics clean.

Run (needs ``DATABASE_URL`` / the app's configured Supabase connection):

    cd backend
    python -m scripts.seed_leaderboard_users --dry-run     # preview, no writes
    python -m scripts.seed_leaderboard_users               # apply
    python -m scripts.seed_leaderboard_users --topup 12    # + livelier streaks
    python -m scripts.seed_leaderboard_users --reset       # detach dummy users

Reversible: every demo user id is prefixed ``usr-dummy-``; ``--reset`` nulls
``user_id`` on votes currently pointing at them (synthesized top-up votes are
deleted).
"""

import argparse
import asyncio
import hashlib
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from app.database import async_session_factory
from app.models.user import User, UserRole
from app.models.user_building_access import UserBuildingAccess
from app.models.vote import Vote, VoteStatus

DEFAULT_BUILDING = "bldg-8f2fd3cf"  # Fluwelen Burgwal 58 - Den Haag (Priva)

# Dummy occupants — Dutch names. Order matters: earlier = heavier weight, so the
# leaderboard has a believable spread of power-contributors and casual voters.
DUMMY_USERS: list[tuple[str, str]] = [
    ("sanne-de-vries", "Sanne de Vries"),
    ("daan-jansen", "Daan Jansen"),
    ("lotte-bakker", "Lotte Bakker"),
    ("bram-van-dijk", "Bram van Dijk"),
    ("femke-visser", "Femke Visser"),
    ("sven-mulder", "Sven Mulder"),
    ("anouk-de-boer", "Anouk de Boer"),
    ("thijs-smit", "Thijs Smit"),
    ("lieke-meijer", "Lieke Meijer"),
    ("jeroen-kok", "Jeroen Kok"),
]


def _uid(slug: str) -> str:
    return f"usr-dummy-{slug}"


def _weights(n: int) -> list[float]:
    """Zipf-ish descending weights, normalised to sum to 1.0."""
    raw = [1.0 / ((i + 1) ** 0.8) for i in range(n)]
    total = sum(raw)
    return [w / total for w in raw]


def _cumulative(weights: list[float]) -> list[float]:
    out, acc = [], 0.0
    for w in weights:
        acc += w
        out.append(acc)
    return out


def _bucket_for(key: str, cumulative: list[float]) -> int:
    """Map a stable hash of ``key`` into [0,1) and pick a weighted bucket."""
    h = int(hashlib.md5(key.encode()).hexdigest(), 16) % 1_000_000
    frac = h / 1_000_000
    for idx, edge in enumerate(cumulative):
        if frac < edge:
            return idx
    return len(cumulative) - 1


async def _ensure_users(session, dry_run: bool) -> None:
    existing = await session.execute(
        select(User.id).where(User.id.in_([_uid(s) for s, _ in DUMMY_USERS]))
    )
    have = {row[0] for row in existing.all()}
    created = 0
    for slug, name in DUMMY_USERS:
        uid = _uid(slug)
        if uid in have:
            continue
        created += 1
        if not dry_run:
            session.add(
                User(
                    id=uid,
                    email=f"{slug}@demo.comfortos.nl",
                    name=name,
                    hashed_password="FIREBASE_MANAGED",
                    role=UserRole.occupant,
                    tenant_id=None,
                    claims={"scopes": ["vote", "view_dashboard"], "demo": True},
                )
            )
    print(f"  users: {len(have)} existing, {created} to create")


async def _ensure_access(session, building_id: str, dry_run: bool) -> None:
    existing = await session.execute(
        select(UserBuildingAccess.id).where(
            UserBuildingAccess.id.in_([f"uba-dummy-{s}" for s, _ in DUMMY_USERS])
        )
    )
    have = {row[0] for row in existing.all()}
    created = 0
    for slug, _ in DUMMY_USERS:
        gid = f"uba-dummy-{slug}"
        if gid in have:
            continue
        created += 1
        if not dry_run:
            session.add(
                UserBuildingAccess(
                    id=gid,
                    user_id=_uid(slug),
                    building_id=building_id,
                    granted_by=None,
                )
            )
    print(f"  access grants: {len(have)} existing, {created} to create")


async def _reassign_votes(session, building_id: str, dry_run: bool) -> None:
    result = await session.execute(
        select(Vote).where(Vote.building_id == building_id)
    )
    votes = result.scalars().all()
    if not votes:
        print(f"  reassign: no votes found for {building_id} (use --topup to add some)")
        return

    weights = _weights(len(DUMMY_USERS))
    cumulative = _cumulative(weights)
    tally: dict[str, int] = {}
    for v in votes:
        idx = _bucket_for(v.vote_uuid, cumulative)
        slug = DUMMY_USERS[idx][0]
        uid = _uid(slug)
        tally[uid] = tally.get(uid, 0) + 1
        if not dry_run:
            v.user_id = uid

    print(f"  reassign: {len(votes)} votes →")
    for slug, name in DUMMY_USERS:
        print(f"      {name:<22} {tally.get(_uid(slug), 0):>4}")


async def _topup(session, building_id: str, n: int, dry_run: bool) -> None:
    if n <= 0:
        return
    now = datetime.now(timezone.utc)
    added = 0
    for slug, _ in DUMMY_USERS:
        uid = _uid(slug)
        for i in range(n):
            vote_uuid = f"dummy-{building_id}-{slug}-{i}"
            exists = await session.execute(
                select(Vote.vote_uuid).where(Vote.vote_uuid == vote_uuid)
            )
            if exists.scalar_one_or_none() is not None:
                continue
            # Spread one vote per day over consecutive recent days → real streaks.
            day_offset = i % 14
            created = (now - timedelta(days=day_offset)).replace(
                hour=9 + (i % 6), minute=0, second=0, microsecond=0
            )
            # Mild per-user thermal bias so analytics still looks heterogeneous.
            thermal = ((int(hashlib.md5((slug + str(i)).encode()).hexdigest(), 16)) % 5) - 2
            added += 1
            if not dry_run:
                session.add(
                    Vote(
                        vote_uuid=vote_uuid,
                        building_id=building_id,
                        user_id=uid,
                        payload={"thermal_comfort": thermal, "zone": "demo"},
                        schema_version=2,
                        status=VoteStatus.confirmed,
                        created_at=created,
                    )
                )
    print(f"  topup: {added} synthesized votes ({n}/user over up to 14 days)")


async def _reset(session, building_id: str, dry_run: bool) -> None:
    dummy_ids = [_uid(s) for s, _ in DUMMY_USERS]
    # Delete synthesized top-up votes
    syn = await session.execute(
        select(Vote).where(
            Vote.building_id == building_id,
            Vote.vote_uuid.like(f"dummy-{building_id}-%"),
        )
    )
    syn_votes = syn.scalars().all()
    # Detach reassigned real votes
    real = await session.execute(
        select(Vote).where(
            Vote.building_id == building_id,
            Vote.user_id.in_(dummy_ids),
            Vote.vote_uuid.notlike(f"dummy-{building_id}-%"),
        )
    )
    real_votes = real.scalars().all()
    print(f"  reset: delete {len(syn_votes)} synthesized, detach {len(real_votes)} real votes")
    if not dry_run:
        for v in syn_votes:
            await session.delete(v)
        for v in real_votes:
            v.user_id = None


async def run(building_id: str, dry_run: bool, topup: int, reset: bool) -> None:
    mode = "DRY-RUN (no writes)" if dry_run else "APPLY"
    print(f"seed_leaderboard_users — building={building_id} mode={mode}")
    async with async_session_factory() as session:
        if reset:
            await _reset(session, building_id, dry_run)
        else:
            await _ensure_users(session, dry_run)
            await _ensure_access(session, building_id, dry_run)
            await _reassign_votes(session, building_id, dry_run)
            await _topup(session, building_id, topup, dry_run)

        if dry_run:
            await session.rollback()
            print("done (dry-run, rolled back).")
        else:
            await session.commit()
            print("done (committed).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--building", default=DEFAULT_BUILDING, help="Building id")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--topup", type=int, default=0, help="Synthesized votes per user")
    parser.add_argument("--reset", action="store_true", help="Detach dummy users / delete top-up votes")
    args = parser.parse_args()
    # Windows consoles default to cp1252 and choke on the arrow/dash glyphs.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(run(args.building, args.dry_run, args.topup, args.reset))


if __name__ == "__main__":
    main()
