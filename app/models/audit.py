"""Audit log for configuration changes and admin actions."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AuditLog(Base):
    """Immutable audit trail — stored in Platform DB."""
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"aud-{uuid.uuid4().hex[:8]}"
    )
    tenant_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
