"""Building telemetry — time-series sensor data ingested from building services.

Stores per-reading environmental measurements (temperature, CO2, noise,
humidity, etc.) keyed by building, metric type, and optional zone/floor.

Building service connectors push data via the Telemetry Ingestion API.
The frontend queries aggregated time-series for the Building Analytics page.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Float,
    DateTime,
    ForeignKey,
    Index,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class TelemetryReading(Base):
    """A single time-stamped sensor reading from a building service.

    Metric types
    ------------
    - ``temperature``  — degrees Celsius
    - ``co2``          — parts per million (ppm)
    - ``noise``        — decibels (dBA)
    - ``humidity``     — percent (%)

    Custom metric types are also accepted; the frontend renders any
    metric it recognises and ignores the rest.

    Spatial granularity
    -------------------
    ``floor`` and ``zone`` are optional free-text labels.  A reading
    with both NULL means "whole building".  The building developer
    decides what granularity to report.
    """

    __tablename__ = "telemetry_readings"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"tr-{uuid.uuid4().hex[:12]}"
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False
    )
    metric_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="temperature | co2 | noise | humidity | custom",
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(
        String(20), nullable=False, default="",
        comment="°C, ppm, dBA, %, etc.",
    )
    floor: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Floor label (optional)"
    )
    zone: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Zone label (optional)"
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="When the sensor captured this reading",
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        comment="When the platform received this reading",
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True,
        comment="Arbitrary extra context (sensor_id, device, etc.)",
    )

    # ── Composite indexes for typical query patterns ──
    __table_args__ = (
        Index(
            "ix_telemetry_building_metric_time",
            "building_id", "metric_type", "recorded_at",
        ),
        Index(
            "ix_telemetry_building_floor_time",
            "building_id", "floor", "recorded_at",
        ),
    )

    def to_api_dict(self) -> dict:
        return {
            "id": self.id,
            "buildingId": self.building_id,
            "metricType": self.metric_type,
            "value": self.value,
            "unit": self.unit,
            "floor": self.floor,
            "zone": self.zone,
            "recordedAt": self.recorded_at.isoformat(),
            "ingestedAt": self.ingested_at.isoformat(),
            "metadata": self.metadata_,
        }
