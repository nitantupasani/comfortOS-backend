"""BuildingTenant junction model — maps tenants to buildings with location info.

A single building can host multiple tenants (e.g., Tesla on Floor 3, Google
on Floor 4). Each row defines *where* inside the building the tenant operates.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class BuildingTenant(Base):
    """Many-to-many junction between buildings and tenants.

    Attributes:
        floors:  JSON list of floor descriptors the tenant occupies,
                 e.g. [{"id": "F3", "label": "Floor 3"}]
        zones:   JSON list of zone descriptors within those floors,
                 e.g. [{"id": "F3-Z1", "label": "Tesla Open Office"}]
    """
    __tablename__ = "building_tenants"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        default=lambda: f"bt-{uuid.uuid4().hex[:8]}",
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id"), nullable=False, index=True
    )
    floors: Mapped[dict | None] = mapped_column(JSON)
    zones: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    building = relationship("Building", back_populates="building_tenants")
    tenant = relationship("Tenant", back_populates="building_tenants")

    def to_api_dict(self) -> dict:
        """Serialise to the JSON shape expected by the frontend."""
        return {
            "id": self.id,
            "buildingId": self.building_id,
            "tenantId": self.tenant_id,
            "floors": self.floors,
            "zones": self.zones,
            "isActive": self.is_active,
        }
