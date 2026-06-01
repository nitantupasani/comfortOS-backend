"""Occupant gamification scoring — eco-points, tiers, and voting streaks.

Single source of truth for the leaderboard maths so every client (web today,
Flutter later) ranks occupants identically. Pure functions, no DB access.

Model
-----
- ``votes``        : number of confirmed comfort votes by the occupant.
- ``best_streak``  : longest run of consecutive calendar days with >=1 vote.
- ``eco_points``   : ``votes * POINTS_PER_VOTE + best_streak * POINTS_PER_STREAK_DAY``.
- ``tier``         : the occupant's tree stage, derived from ``eco_points``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

POINTS_PER_VOTE = 10
POINTS_PER_STREAK_DAY = 20

# Ordered low → high. ``min_points`` is the inclusive lower bound for the tier.
TIERS: list[dict] = [
    {"key": "seedling", "label": "Seedling", "min_points": 0},
    {"key": "sapling", "label": "Sapling", "min_points": 100},
    {"key": "young", "label": "Young Tree", "min_points": 300},
    {"key": "tree", "label": "Tree", "min_points": 600},
    {"key": "forest", "label": "Forest", "min_points": 1000},
]

# A "grown tree" (used for the treesGrown summary stat) is this tier or above.
GROWN_TREE_TIER_KEY = "tree"
GROWN_TREE_MIN_POINTS = next(t["min_points"] for t in TIERS if t["key"] == GROWN_TREE_TIER_KEY)


def eco_points(votes: int, best_streak: int) -> int:
    """Composite contribution score: base per vote plus a streak bonus."""
    return votes * POINTS_PER_VOTE + best_streak * POINTS_PER_STREAK_DAY


def tier_for(points: int) -> dict:
    """Return the tier for an eco-points total.

    Shape: ``{key, label, min_points, next_label, next_points, progress}`` where
    ``progress`` is 0..1 toward the next tier (1.0 when already at the top tier).
    """
    current = TIERS[0]
    current_idx = 0
    for idx, t in enumerate(TIERS):
        if points >= t["min_points"]:
            current = t
            current_idx = idx
        else:
            break

    is_top = current_idx >= len(TIERS) - 1
    if is_top:
        return {
            **current,
            "next_label": None,
            "next_points": None,
            "progress": 1.0,
        }

    nxt = TIERS[current_idx + 1]
    span = nxt["min_points"] - current["min_points"]
    progress = (points - current["min_points"]) / span if span > 0 else 1.0
    return {
        **current,
        "next_label": nxt["label"],
        "next_points": nxt["min_points"],
        "progress": max(0.0, min(1.0, progress)),
    }


def compute_streaks(dates: Iterable[date]) -> tuple[int, int]:
    """Return ``(current_streak, best_streak)`` from a set of vote dates.

    ``best_streak`` is the longest run of consecutive calendar days anywhere in
    the history. ``current_streak`` is the run ending on the **most recent** vote
    day (anchored to the data, not wall-clock "today", so demo/stale data still
    shows a streak). Both are 0 when there are no votes.
    """
    unique = sorted(set(dates))
    if not unique:
        return 0, 0

    best = 1
    run = 1
    for prev, cur in zip(unique, unique[1:]):
        if cur - prev == timedelta(days=1):
            run += 1
        else:
            run = 1
        best = max(best, run)

    # Current streak: walk backward from the latest vote day.
    current = 1
    for prev, cur in zip(reversed(unique), reversed(unique[:-1])):
        # ``prev`` is later, ``cur`` is earlier (reversed iteration)
        if prev - cur == timedelta(days=1):
            current += 1
        else:
            break

    return current, best
