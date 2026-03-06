"""Tenant model — organisational isolation boundary.

A tenant represents a company/organisation (e.g. Tesla, Google) that occupies
space inside one or more buildings.  The `email_domain` field enables
domain-based onboarding: any user whose e-mail ends with that domain can
automatically join the tenant.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"tenant-{uuid.uuid4().hex[:8]}"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email_domain: Mapped[str | None] = mapped_column(
        String(200), unique=True, index=True,
        comment="e.g. tesla.com — users with this e-mail domain can self-onboard",
    )
    auth_provider: Mapped[str | None] = mapped_column(
        String(100),
        comment="Third-party IdP slug (e.g. google, okta, azure-ad) for SSO",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    users = relationship("User", back_populates="tenant", lazy="selectin")
    building_tenants = relationship(
        "BuildingTenant", back_populates="tenant", lazy="selectin"
    )
