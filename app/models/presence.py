"""Presence models — events and BLE beacon registry."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class PresenceEvent(Base):
    """A single presence check-in event reported by a mobile client."""
    __tablename__ = "presence_events"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"pe-{uuid.uuid4().hex[:8]}"
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)  # qr, wifi, ble, manual
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Beacon(Base):
    """Registered BLE beacon associated with a building."""
    __tablename__ = "beacons"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"bcn-{uuid.uuid4().hex[:8]}"
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True
    )
    uuid_str: Mapped[str] = mapped_column("uuid", String(100), nullable=False)
    major: Mapped[int | None] = mapped_column()
    minor: Mapped[int | None] = mapped_column()
    label: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    building = relationship("Building", back_populates="beacons")

    def to_api_dict(self) -> dict:
        return {
            "id": self.id,
            "buildingId": self.building_id,
            "uuid": self.uuid_str,
            "major": self.major,
            "minor": self.minor,
            "label": self.label,
        }
