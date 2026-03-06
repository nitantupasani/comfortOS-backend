"""Push notification token registration."""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class PushToken(Base):
    """Device push token for FCM/APNs delivery."""
    __tablename__ = "push_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=False, index=True
    )
    push_token: Mapped[str] = mapped_column(String(500), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(20))  # android, ios, web
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
