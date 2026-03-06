"""Building SDUI configuration — versioned dashboard + vote-form + location-form."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class BuildingConfig(Base):
    """Stores per-building SDUI configs (dashboard, vote form, location form).

    Each row represents a configuration version. Only the latest
    active row per building is served to clients.
    """
    __tablename__ = "building_configs"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"cfg-{uuid.uuid4().hex[:8]}"
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    dashboard_layout: Mapped[dict | None] = mapped_column(JSON)
    vote_form_schema: Mapped[dict | None] = mapped_column(JSON)
    location_form_config: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    building = relationship("Building", back_populates="configs")
