"""Location model -- tree-based physical hierarchy for buildings.

Canonical reference hierarchy:
    Building -> Block/Wing -> Floor -> Room -> Placement

Rules:
- Building is the root node (parent_id = NULL).
- Block/Wing, Floor, and Placement are optional levels.
- Room is the main operational spatial unit.
- Intermediate levels can be skipped; children link directly to the
  nearest existing ancestor via parent_id.
- Every node carries building_id for fast filtering.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        default=lambda: f"loc-{uuid.uuid4().hex[:8]}",
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("locations.id"), nullable=True, index=True,
        comment="NULL only for root building node",
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="building | block_or_wing | floor | room | placement",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Short machine-readable code, e.g. 'F2', 'R201'",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Display ordering within the same parent",
    )
    orientation: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="north, south_east, street_side, courtyard_side, etc.",
    )
    usage_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="office, lecture_hall, meeting_room, lab, corridor, etc.",
    )
    external_refs: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment='Key-value map to external IDs, e.g. {"bms_zone": "ST01"}',
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True,
        comment="Arbitrary extra properties (area_m2, capacity, etc.)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Self-referential relationship
    children = relationship(
        "Location",
        back_populates="parent",
        lazy="noload",
        foreign_keys="[Location.parent_id]",
    )
    parent = relationship(
        "Location",
        back_populates="children",
        remote_side="Location.id",
        lazy="noload",
        foreign_keys="[Location.parent_id]",
    )

    # Relationship to building
    building = relationship("Building", backref="locations", lazy="noload")

    __table_args__ = (
        Index("ix_location_building_type", "building_id", "type"),
        Index("ix_location_building_parent", "building_id", "parent_id"),
    )

    # Controlled type values
    VALID_TYPES = {"building", "block_or_wing", "floor", "room", "placement"}
    TYPE_LEVEL = {
        "building": 0,
        "block_or_wing": 1,
        "floor": 2,
        "room": 3,
        "placement": 4,
    }

    def to_api_dict(self) -> dict:
        return {
            "id": self.id,
            "buildingId": self.building_id,
            "parentId": self.parent_id,
            "type": self.type,
            "name": self.name,
            "code": self.code,
            "sortOrder": self.sort_order,
            "orientation": self.orientation,
            "usageType": self.usage_type,
            "externalRefs": self.external_refs,
            "metadata": self.metadata_,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
