"""UserBuildingAccess junction model — explicit per-user building access grants.

Allows FM / Admin users to grant individual occupants access to specific
buildings.  This supplements the automatic tenant-based access (if a user's
tenant is mapped to a building via ``building_tenants``, they get access
automatically).

Access resolution order
-----------------------
1. **Open buildings** (``requires_access_permission=False``) → everyone.
2. **Restricted buildings** → access if ANY of:
   a. Caller is admin or building FM.
   b. Caller's tenant is mapped via ``building_tenants``.
   c. Caller has an explicit ``UserBuildingAccess`` grant (this table).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class UserBuildingAccess(Base):
    """Many-to-many junction between users and buildings they may access."""

    __tablename__ = "user_building_access"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        default=lambda: f"uba-{uuid.uuid4().hex[:8]}",
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=False, index=True,
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True,
    )
    granted_by: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("users.id"),
        nullable=True,
        comment="User who granted this access (NULL for system / self-assigned)",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user = relationship("User", back_populates="building_accesses", foreign_keys=[user_id])
    building = relationship("Building", back_populates="user_accesses")
    granter = relationship("User", foreign_keys=[granted_by])

    def to_api_dict(self) -> dict:
        """Serialise to the JSON shape expected by the frontend."""
        return {
            "id": self.id,
            "userId": self.user_id,
            "buildingId": self.building_id,
            "grantedBy": self.granted_by,
            "isActive": self.is_active,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
