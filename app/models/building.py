"""Building model with geolocation — multi-tenant capable.

A building is a *physical* structure.  One or more tenants can occupy
different floors / zones inside the same building via the `BuildingTenant`
junction table.

Access modes
------------
- **Open** (`requires_access_permission=False`, the default):  Any
  authenticated user can view the building, vote, and report presence.
- **Restricted** (`requires_access_permission=True`):  Only users whose
  tenant is mapped to this building (via ``building_tenants``) may access it.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, Integer, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"bldg-{uuid.uuid4().hex[:8]}"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    requires_access_permission: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        comment="When True, only tenant-mapped users may access this building",
    )
    daily_vote_limit: Mapped[int] = mapped_column(
        Integer,
        default=10,
        server_default="10",
        comment="Max votes a single user may submit per calendar day",
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    building_tenants = relationship(
        "BuildingTenant", back_populates="building", lazy="selectin"
    )
    configs = relationship("BuildingConfig", back_populates="building", lazy="selectin")
    votes = relationship("Vote", back_populates="building", lazy="noload")
    beacons = relationship("Beacon", back_populates="building", lazy="selectin")
    user_accesses = relationship(
        "UserBuildingAccess", back_populates="building", lazy="noload",
    )

    def to_api_dict(self, tenant_id: str | None = None) -> dict:
        """Serialise to the JSON shape expected by the Flutter frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "tenantId": tenant_id,
            "city": self.city,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "requiresAccessPermission": self.requires_access_permission,
            "dailyVoteLimit": self.daily_vote_limit,
            "metadata": self.metadata_,
        }
