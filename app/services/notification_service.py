"""
Push notification service — FCM-based delivery to mobile devices.

Maps to the C4 'Push Provider' container in backend.puml.

Firebase Admin SDK (already initialized for auth) provides the messaging
module that handles both Android (FCM) and iOS (APNs) delivery.
"""

import logging
from typing import Sequence

from firebase_admin import messaging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.notification import PushToken

logger = logging.getLogger("comfortos.notifications")


async def _resolve_tokens(
    db: AsyncSession,
    *,
    user_ids: list[str] | None = None,
    building_id: str | None = None,
) -> list[str]:
    """Fetch device tokens for the target audience.

    Priority:
      1. Explicit user_ids  → tokens for those users.
      2. building_id only   → all tokens (broadcast to building occupants
         would need a join through presence or access; for now returns all).
    """
    stmt = select(PushToken.push_token)

    if user_ids:
        stmt = stmt.where(PushToken.user_id.in_(user_ids))

    result = await db.execute(stmt)
    return list(result.scalars().all())


def _build_message(
    token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> messaging.Message:
    """Build a single FCM Message object."""
    return messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
        token=token,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="comfortos_default",
            ),
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", badge=1),
            ),
        ),
    )


async def send_to_users(
    db: AsyncSession,
    user_ids: list[str],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict:
    """Send a notification to specific users by their user IDs."""
    tokens = await _resolve_tokens(db, user_ids=user_ids)
    if not tokens:
        return {"sent": 0, "failed": 0, "detail": "No registered tokens"}

    return _send_batch(tokens, title, body, data)


async def send_broadcast(
    db: AsyncSession,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict:
    """Broadcast a notification to all registered devices."""
    tokens = await _resolve_tokens(db)
    if not tokens:
        return {"sent": 0, "failed": 0, "detail": "No registered tokens"}

    return _send_batch(tokens, title, body, data)


def _send_batch(
    tokens: Sequence[str],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> dict:
    """Send notifications to a list of device tokens via FCM.

    Uses send_each (non-deprecated batch API) for up to 500 tokens per call.
    """
    messages = [_build_message(t, title, body, data) for t in tokens]

    success_count = 0
    failure_count = 0

    # FCM send_each supports up to 500 messages per call
    batch_size = 500
    for i in range(0, len(messages), batch_size):
        batch = messages[i : i + batch_size]
        try:
            response: messaging.BatchResponse = messaging.send_each(batch)
            success_count += response.success_count
            failure_count += response.failure_count
        except Exception:
            logger.exception("FCM send_each failed for batch starting at %d", i)
            failure_count += len(batch)

    logger.info(
        "Push notification: sent=%d failed=%d total_tokens=%d",
        success_count,
        failure_count,
        len(tokens),
    )
    return {"sent": success_count, "failed": failure_count}
