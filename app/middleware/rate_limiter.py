"""
Simple in-memory rate limiter middleware.

In production, replace with Redis-backed sliding window.
"""

import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limiter."""

    def __init__(self, app):
        super().__init__(app)
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._max = settings.rate_limit_requests
        self._window = settings.rate_limit_window_seconds

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Prune old entries
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if now - t < self._window
        ]

        if len(self._requests[client_ip]) >= self._max:
            return Response(
                content='{"detail": "Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
            )

        self._requests[client_ip].append(now)
        return await call_next(request)
