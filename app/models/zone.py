"""Zone and ZoneMember models -- logical/operational room groupings.

Zones are separate from the physical location hierarchy.  A zone groups
one or more rooms (and optionally placements) for purposes such as HVAC
control, comfort analytics, dashboards, or operational reporting.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        default=lambda: f"zone-{uuid.uuid4().hex[:8]}",
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    zone_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="hvac, comfort, analytics, control, dashboard",
    )
    external_refs: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment='External zone identifiers, e.g. {"bms_zone_group": "HVAC-N-F2"}',
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    building = relationship("Building", backref="zones", lazy="noload")
    members = relationship("ZoneMember", back_populates="zone", lazy="selectin")

    def to_api_dict(self) -> dict:
        return {
            "id": self.id,
            "buildingId": self.building_id,
            "name": self.name,
            "zoneType": self.zone_type,
            "externalRefs": self.external_refs,
            "metadata": self.metadata_,
            "createdAt": self.created_at.isoformat(),
            "members": [m.to_api_dict() for m in (self.members or [])],
        }


class ZoneMember(Base):
    __tablename__ = "zone_members"

    zone_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("zones.id", ondelete="CASCADE"),
        primary_key=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("locations.id"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    zone = relationship("Zone", back_populates="members")
    location = relationship("Location", lazy="selectin")

    __table_args__ = (
        Index("ix_zone_member_location", "location_id"),
    )

    def to_api_dict(self) -> dict:
        return {
            "zoneId": self.zone_id,
            "locationId": self.location_id,
        }
