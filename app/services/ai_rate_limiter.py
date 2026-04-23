"""In-memory sliding-window rate limiter for the Vos AI endpoints.

Two separate buckets:

- per-user for POST /ai/chat (authenticated, tool-amplified)
- per-IP for POST /ai/chat/public (unauth, one Gemini call each)

Each bucket enforces both an hourly and a daily limit. The defaults live
in app.config.Settings and are sized so that 10 authenticated users plus
25 landing-page IPs stay under the Gemini 2.0 Flash free tier.

Replace with a Redis-backed store if the API ever runs on multiple
worker processes.
"""

from __future__ import annotations

import time
from collections import defaultdict

from ..config import settings

_HOUR = 3600
_DAY = 86400


class _Bucket:
    """Sliding window of hit timestamps for one key."""

    __slots__ = ("hits",)

    def __init__(self) -> None:
        self.hits: list[float] = []

    def check_and_record(
        self,
        now: float,
        hourly_limit: int,
        daily_limit: int,
    ) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds).

        If the request is allowed the call is recorded before returning.
        """
        day_ago = now - _DAY
        if self.hits and self.hits[0] < day_ago:
            self.hits = [t for t in self.hits if t >= day_ago]

        if len(self.hits) >= daily_limit:
            oldest = self.hits[0]
            return False, max(1, int(oldest + _DAY - now) + 1)

        hour_ago = now - _HOUR
        hourly = 0
        oldest_in_hour: float | None = None
        for t in self.hits:
            if t >= hour_ago:
                hourly += 1
                if oldest_in_hour is None:
                    oldest_in_hour = t
        if hourly >= hourly_limit:
            assert oldest_in_hour is not None
            return False, max(1, int(oldest_in_hour + _HOUR - now) + 1)

        self.hits.append(now)
        return True, 0


class AiRateLimiter:
    def __init__(self) -> None:
        self._user_buckets: dict[str, _Bucket] = defaultdict(_Bucket)
        self._ip_buckets: dict[str, _Bucket] = defaultdict(_Bucket)

    def check_user(self, user_id: str) -> tuple[bool, int]:
        return self._user_buckets[user_id].check_and_record(
            time.time(),
            hourly_limit=settings.ai_rate_limit_user_hourly,
            daily_limit=settings.ai_rate_limit_user_daily,
        )

    def check_public_ip(self, ip: str) -> tuple[bool, int]:
        return self._ip_buckets[ip].check_and_record(
            time.time(),
            hourly_limit=settings.ai_rate_limit_public_hourly,
            daily_limit=settings.ai_rate_limit_public_daily,
        )


ai_rate_limiter = AiRateLimiter()
