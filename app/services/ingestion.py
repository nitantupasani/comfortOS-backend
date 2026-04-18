"""Telemetry ingestion and normalization service.

Implements the three-layer normalization pipeline:
  1. Source Integration Layer -- accepts raw data from push or pull
  2. Normalization Layer     -- resolves locations, sensors, validates, flags
  3. Storage Layer           -- writes uniform rows to telemetry_readings

All building-specific behavior is driven by configuration (endpoint
response_format, location external_refs, sensor source_identifier,
building_telemetry_config).  No per-building custom code.
"""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.location import Location
from ..models.sensor import Sensor
from ..models.telemetry import TelemetryReading
from ..models.building_telemetry_config import BuildingTelemetryConfig
from ..schemas.telemetry import TelemetryReadingIn

logger = logging.getLogger("comfortos.ingestion")

# Maximum future tolerance and age for readings
_FUTURE_TOLERANCE = timedelta(minutes=5)
_MAX_AGE = timedelta(days=30)


class NormalizedReading:
    """Internal representation after normalization, before storage."""

    __slots__ = (
        "building_id", "location_id", "sensor_id", "metric_type",
        "value", "unit", "recorded_at", "source_level",
        "aggregation_method", "quality_flag", "connector_id", "metadata",
        "floor", "zone", "error",
    )

    def __init__(self) -> None:
        self.building_id: str = ""
        self.location_id: str | None = None
        self.sensor_id: str | None = None
        self.metric_type: str = ""
        self.value: float = 0.0
        self.unit: str = ""
        self.recorded_at: datetime | None = None
        self.source_level: str | None = None
        self.aggregation_method: str = "raw"
        self.quality_flag: str = "good"
        self.connector_id: str | None = None
        self.metadata: dict | None = None
        self.floor: str | None = None
        self.zone: str | None = None
        self.error: str | None = None


class IngestionService:
    """Stateless normalization pipeline for telemetry data."""

    async def normalize_and_store(
        self,
        db: AsyncSession,
        building_id: str,
        readings: list[TelemetryReadingIn],
        connector_id: str | None = None,
        normalization_profile: dict | None = None,
        location_mapping: dict | None = None,
        sensor_mapping: dict | None = None,
    ) -> tuple[int, int, list[dict]]:
        """Normalize a batch of readings and store valid ones.

        Returns (accepted_count, rejected_count, error_details).
        """
        # Pre-load lookup caches for this building
        locations_by_ref = await self._load_location_refs(db, building_id)
        locations_by_name = await self._load_location_names(db, building_id)
        locations_by_id = await self._load_location_ids(db, building_id)
        sensors_by_ref = await self._load_sensor_refs(db, building_id)
        metric_configs = await self._load_metric_configs(db, building_id)

        profile = normalization_profile or {}
        metric_type_map = profile.get("metric_type_map", {})
        unit_map = profile.get("unit_map", {})

        accepted = []
        errors = []

        for i, reading in enumerate(readings):
            nr = self._normalize_one(
                reading=reading,
                building_id=building_id,
                connector_id=connector_id,
                locations_by_ref=locations_by_ref,
                locations_by_name=locations_by_name,
                locations_by_id=locations_by_id,
                sensors_by_ref=sensors_by_ref,
                metric_configs=metric_configs,
                metric_type_map=metric_type_map,
                unit_map=unit_map,
                location_mapping=location_mapping,
            )

            if nr.error:
                errors.append({"index": i, "error": nr.error})
                continue

            accepted.append(nr)

        # Bulk insert accepted readings
        if accepted:
            rows = [
                TelemetryReading(
                    building_id=nr.building_id,
                    location_id=nr.location_id,
                    sensor_id=nr.sensor_id,
                    metric_type=nr.metric_type,
                    value=nr.value,
                    unit=nr.unit,
                    recorded_at=nr.recorded_at,
                    source_level=nr.source_level,
                    aggregation_method=nr.aggregation_method,
                    quality_flag=nr.quality_flag,
                    connector_id=nr.connector_id,
                    metadata_=nr.metadata,
                    floor=nr.floor,
                    zone=nr.zone,
                )
                for nr in accepted
            ]
            db.add_all(rows)
            await db.flush()

        return len(accepted), len(errors), errors

    def _normalize_one(
        self,
        reading: TelemetryReadingIn,
        building_id: str,
        connector_id: str | None,
        locations_by_ref: dict[str, str],
        locations_by_name: dict[str, str],
        locations_by_id: set[str],
        sensors_by_ref: dict[str, tuple[str, str | None, dict | None]],
        metric_configs: dict[str, BuildingTelemetryConfig],
        metric_type_map: dict[str, str],
        unit_map: dict[str, str],
        location_mapping: dict | None,
    ) -> NormalizedReading:
        nr = NormalizedReading()
        nr.building_id = building_id
        nr.connector_id = connector_id
        nr.metadata = reading.metadata
        nr.floor = reading.floor
        nr.zone = reading.zone

        # Step 1: Validate required fields
        if reading.value is None:
            nr.error = "missing value"
            return nr
        if reading.recordedAt is None:
            nr.error = "missing recorded_at"
            return nr

        # Step 2: Metric type mapping
        raw_metric = reading.metricType
        nr.metric_type = metric_type_map.get(raw_metric, raw_metric)

        # Step 3: Value
        try:
            nr.value = float(reading.value)
        except (ValueError, TypeError):
            nr.error = f"non-numeric value: {reading.value}"
            return nr

        # Step 4: Timestamp
        nr.recorded_at = reading.recordedAt
        if nr.recorded_at.tzinfo is None:
            nr.recorded_at = nr.recorded_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if nr.recorded_at > now + _FUTURE_TOLERANCE:
            nr.quality_flag = "suspect"
        if nr.recorded_at < now - _MAX_AGE:
            nr.quality_flag = "suspect"

        # Step 5: Unit mapping and inference
        raw_unit = reading.unit
        if raw_unit:
            nr.unit = unit_map.get(raw_unit, raw_unit)
        else:
            config = metric_configs.get(nr.metric_type)
            if config and config.default_unit:
                nr.unit = config.default_unit
            else:
                nr.unit = BuildingTelemetryConfig.DEFAULT_UNITS.get(nr.metric_type, "")

        # Step 6: Location resolution
        location_id = self._resolve_location(
            reading=reading,
            locations_by_ref=locations_by_ref,
            locations_by_name=locations_by_name,
            locations_by_id=locations_by_id,
            location_mapping=location_mapping,
        )
        nr.location_id = location_id

        # Step 7: Sensor resolution
        sensor_id = None
        if reading.sensorRef:
            sensor_data = sensors_by_ref.get(reading.sensorRef)
            if sensor_data:
                sensor_id = sensor_data[0]
                # If location was not resolved from reading, use sensor's location
                if not nr.location_id and sensor_data[1]:
                    nr.location_id = sensor_data[1]
                # Apply calibration offset
                cal = sensor_data[2]
                if cal and nr.metric_type in cal:
                    nr.value += cal[nr.metric_type]
        nr.sensor_id = sensor_id

        # Step 8: Source level
        if reading.sourceLevel:
            nr.source_level = reading.sourceLevel
        elif sensor_id:
            nr.source_level = "sensor"
        elif nr.location_id:
            nr.source_level = "room"
        else:
            nr.source_level = "building"

        # Step 9: Aggregation method
        nr.aggregation_method = reading.aggregationMethod or "raw"

        # Step 10: Quality flag (override only if not already set to suspect)
        if reading.qualityFlag:
            nr.quality_flag = reading.qualityFlag
        config = metric_configs.get(nr.metric_type)
        if config and nr.quality_flag == "good":
            if config.valid_range_min is not None and nr.value < config.valid_range_min:
                nr.quality_flag = "out_of_range"
            if config.valid_range_max is not None and nr.value > config.valid_range_max:
                nr.quality_flag = "out_of_range"

        return nr

    def _resolve_location(
        self,
        reading: TelemetryReadingIn,
        locations_by_ref: dict[str, str],
        locations_by_name: dict[str, str],
        locations_by_id: set[str],
        location_mapping: dict | None,
    ) -> str | None:
        """Resolve a location identifier from the reading to a location ID.

        Resolution order:
          1. Match locationRef against external_refs values
          2. Match locationRef against location names
          3. Match locationRef against location IDs directly
          4. Try legacy zone field against external_refs
        """
        ref = reading.locationRef
        if ref:
            # External refs match
            if ref in locations_by_ref:
                return locations_by_ref[ref]
            # Name match
            if ref in locations_by_name:
                return locations_by_name[ref]
            # Direct ID match
            if ref in locations_by_id:
                return ref

        # Legacy: try zone field
        if reading.zone:
            if reading.zone in locations_by_ref:
                return locations_by_ref[reading.zone]
            if reading.zone in locations_by_name:
                return locations_by_name[reading.zone]

        return None

    # -- Cache loaders -----------------------------------------------------

    async def _load_location_refs(
        self, db: AsyncSession, building_id: str,
    ) -> dict[str, str]:
        """Build a map: external_ref_value -> location_id for the building."""
        result = await db.execute(
            select(Location.id, Location.external_refs)
            .where(
                Location.building_id == building_id,
                Location.external_refs.isnot(None),
            )
        )
        ref_map: dict[str, str] = {}
        for loc_id, ext_refs in result.all():
            if isinstance(ext_refs, dict):
                for v in ext_refs.values():
                    if isinstance(v, str):
                        ref_map[v] = loc_id
        return ref_map

    async def _load_location_names(
        self, db: AsyncSession, building_id: str,
    ) -> dict[str, str]:
        """Build a map: location_name -> location_id for the building."""
        result = await db.execute(
            select(Location.id, Location.name)
            .where(Location.building_id == building_id)
        )
        return {name: loc_id for loc_id, name in result.all()}

    async def _load_location_ids(
        self, db: AsyncSession, building_id: str,
    ) -> set[str]:
        """Load all location IDs for the building."""
        result = await db.execute(
            select(Location.id)
            .where(Location.building_id == building_id)
        )
        return {row[0] for row in result.all()}

    async def _load_sensor_refs(
        self, db: AsyncSession, building_id: str,
    ) -> dict[str, tuple[str, str | None, dict | None]]:
        """Build a map: source_identifier -> (sensor_id, room_id, calibration_offset)."""
        result = await db.execute(
            select(
                Sensor.sensor_id,
                Sensor.source_identifier,
                Sensor.room_id,
                Sensor.calibration_offset,
            )
            .where(
                Sensor.building_id == building_id,
                Sensor.is_active == True,  # noqa: E712
            )
        )
        ref_map: dict[str, tuple[str, str | None, dict | None]] = {}
        for sensor_id, source_id, room_id, cal in result.all():
            if source_id:
                ref_map[source_id] = (sensor_id, room_id, cal)
            # Also index by sensor_id directly
            ref_map[sensor_id] = (sensor_id, room_id, cal)
        return ref_map

    async def _load_metric_configs(
        self, db: AsyncSession, building_id: str,
    ) -> dict[str, BuildingTelemetryConfig]:
        """Load all metric configs for the building, keyed by metric_type."""
        result = await db.execute(
            select(BuildingTelemetryConfig)
            .where(BuildingTelemetryConfig.building_id == building_id)
        )
        return {c.metric_type: c for c in result.scalars().all()}


# Module-level singleton
ingestion_service = IngestionService()
