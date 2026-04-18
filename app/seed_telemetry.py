"""Seed data for the telemetry integration system.

Creates a complete example building with:
- Full location hierarchy (building, wing, floor, rooms, placements)
- Sensors with multiple metrics and placement-level positioning
- Zones mapping rooms to operational groups
- Telemetry endpoints for all five endpoint modes
- Building telemetry config for all four core metrics
- Example normalized telemetry readings

Run:  python -m app.seed_telemetry
"""

import asyncio
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from .database import async_session_factory, engine, Base
from .models.building import Building
from .models.location import Location
from .models.sensor import Sensor
from .models.zone import Zone, ZoneMember
from .models.telemetry_endpoint import TelemetryEndpoint
from .models.building_telemetry_config import BuildingTelemetryConfig
from .models.telemetry import TelemetryReading


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        # ── Building ─────────────────────────────────────────────────
        building = Building(
            id="bldg-demo",
            name="Demo Building",
            address="Johanna Westerdijkplein 75, 2521 EN Den Haag",
            city="Den Haag",
            latitude=52.0705,
            longitude=4.3254,
        )
        db.add(building)

        # ── Location hierarchy ───────────────────────────────────────
        locations = [
            # Root
            Location(id="loc-demo", building_id="bldg-demo", parent_id=None,
                     type="building", name="Demo Building", code="DEMO",
                     external_refs={"bms_code": "DEMO-MAIN"}),
            # Wings
            Location(id="loc-north", building_id="bldg-demo", parent_id="loc-demo",
                     type="block_or_wing", name="North Wing", code="NW",
                     orientation="north"),
            Location(id="loc-south", building_id="bldg-demo", parent_id="loc-demo",
                     type="block_or_wing", name="South Wing", code="SW",
                     orientation="south"),
            # Floors
            Location(id="loc-nw-f1", building_id="bldg-demo", parent_id="loc-north",
                     type="floor", name="Floor 1", code="NW-F1", sort_order=1),
            Location(id="loc-nw-f2", building_id="bldg-demo", parent_id="loc-north",
                     type="floor", name="Floor 2", code="NW-F2", sort_order=2),
            Location(id="loc-sw-f1", building_id="bldg-demo", parent_id="loc-south",
                     type="floor", name="Floor 1", code="SW-F1", sort_order=1),
            # Rooms
            Location(id="loc-rm101", building_id="bldg-demo", parent_id="loc-nw-f1",
                     type="room", name="Room 1.01", code="R101",
                     usage_type="office",
                     external_refs={"bms_zone": "NW-101", "room_number": "1.01"}),
            Location(id="loc-rm102", building_id="bldg-demo", parent_id="loc-nw-f1",
                     type="room", name="Room 1.02", code="R102",
                     usage_type="meeting_room",
                     external_refs={"bms_zone": "NW-102"}),
            Location(id="loc-rm201", building_id="bldg-demo", parent_id="loc-nw-f2",
                     type="room", name="Room 2.01", code="R201",
                     usage_type="lecture_hall",
                     external_refs={"bms_zone": "NW-201"}),
            Location(id="loc-rm-sw1", building_id="bldg-demo", parent_id="loc-sw-f1",
                     type="room", name="Room S1.01", code="RS101",
                     usage_type="lab",
                     external_refs={"bms_zone": "SW-101"}),
            # Placements (sub-room)
            Location(id="loc-rm101-win", building_id="bldg-demo", parent_id="loc-rm101",
                     type="placement", name="Near Window", code="R101-WIN"),
            Location(id="loc-rm101-cor", building_id="bldg-demo", parent_id="loc-rm101",
                     type="placement", name="Corridor Side", code="R101-COR"),
            Location(id="loc-rm201-ctr", building_id="bldg-demo", parent_id="loc-rm201",
                     type="placement", name="Center", code="R201-CTR"),
        ]
        db.add_all(locations)

        # ── Sensors ──────────────────────────────────────────────────
        sensors = [
            # Room 1.01: two temp sensors at placements + one CO2 at room level
            Sensor(sensor_id="sens-t1-win", building_id="bldg-demo",
                   room_id="loc-rm101", placement_id="loc-rm101-win",
                   sensor_type="thermostat", metric_types=["temperature"],
                   source_identifier="DEMO-NW101-TEMP-A",
                   unit_map={"temperature": "C"},
                   priority=0, is_preferred=True, aggregation_group="main"),
            Sensor(sensor_id="sens-t1-cor", building_id="bldg-demo",
                   room_id="loc-rm101", placement_id="loc-rm101-cor",
                   sensor_type="thermostat", metric_types=["temperature"],
                   source_identifier="DEMO-NW101-TEMP-B",
                   unit_map={"temperature": "C"},
                   priority=1, is_preferred=False, aggregation_group="main"),
            Sensor(sensor_id="sens-co2-101", building_id="bldg-demo",
                   room_id="loc-rm101", placement_id=None,
                   sensor_type="iaq_sensor", metric_types=["co2", "relative_humidity"],
                   source_identifier="DEMO-NW101-IAQ",
                   unit_map={"co2": "ppm", "relative_humidity": "%"},
                   priority=0, is_preferred=True),
            # Room 1.02: one multi-sensor
            Sensor(sensor_id="sens-multi-102", building_id="bldg-demo",
                   room_id="loc-rm102", placement_id=None,
                   sensor_type="multi_sensor",
                   metric_types=["temperature", "co2", "relative_humidity", "noise"],
                   source_identifier="DEMO-NW102-MULTI",
                   unit_map={"temperature": "C", "co2": "ppm", "relative_humidity": "%", "noise": "dBA"},
                   priority=0, is_preferred=True),
            # Room 2.01: temp at center placement + noise at room level
            Sensor(sensor_id="sens-t-201", building_id="bldg-demo",
                   room_id="loc-rm201", placement_id="loc-rm201-ctr",
                   sensor_type="thermostat", metric_types=["temperature"],
                   source_identifier="DEMO-NW201-TEMP",
                   priority=0, is_preferred=True),
            Sensor(sensor_id="sens-noise-201", building_id="bldg-demo",
                   room_id="loc-rm201", placement_id=None,
                   sensor_type="sound_meter", metric_types=["noise"],
                   source_identifier="DEMO-NW201-NOISE",
                   priority=0, is_preferred=True),
            # Room S1.01: one temp sensor (south wing, different endpoint)
            Sensor(sensor_id="sens-t-sw101", building_id="bldg-demo",
                   room_id="loc-rm-sw1", placement_id=None,
                   sensor_type="thermostat", metric_types=["temperature", "relative_humidity"],
                   source_identifier="DEMO-SW101-TEMP",
                   priority=0, is_preferred=True),
        ]
        db.add_all(sensors)

        # ── Zones ────────────────────────────────────────────────────
        zones = [
            Zone(id="zone-hvac-nw", building_id="bldg-demo",
                 name="HVAC Zone North Wing", zone_type="hvac",
                 external_refs={"bms_zone_group": "HVAC-NW"}),
            Zone(id="zone-comfort", building_id="bldg-demo",
                 name="Comfort Monitoring", zone_type="comfort"),
        ]
        db.add_all(zones)
        await db.flush()

        zone_members = [
            ZoneMember(zone_id="zone-hvac-nw", location_id="loc-rm101"),
            ZoneMember(zone_id="zone-hvac-nw", location_id="loc-rm102"),
            ZoneMember(zone_id="zone-hvac-nw", location_id="loc-rm201"),
            ZoneMember(zone_id="zone-comfort", location_id="loc-rm101"),
            ZoneMember(zone_id="zone-comfort", location_id="loc-rm102"),
            ZoneMember(zone_id="zone-comfort", location_id="loc-rm201"),
            ZoneMember(zone_id="zone-comfort", location_id="loc-rm-sw1"),
        ]
        db.add_all(zone_members)

        # ── Telemetry Endpoints ──────────────────────────────────────

        endpoints = [
            # Case A: single_zone -- one endpoint for one room
            TelemetryEndpoint(
                endpoint_id="ep-single",
                building_id="bldg-demo",
                endpoint_name="Room 1.01 Thermostat API",
                endpoint_url="https://thermostat.local/api/room101",
                authentication_config={"type": "api_key", "header": "X-Key", "api_key": "demo-key-1"},
                endpoint_mode="single_zone",
                default_location_id="loc-rm101",
                available_metrics=["temperature", "relative_humidity"],
                response_format={
                    "readings_path": "readings",
                    "fields": {
                        "metric_type": "$.metric",
                        "value": "$.value",
                        "recorded_at": "$.time",
                    },
                },
                location_mapping={"strategy": "fixed"},
                polling_config={"interval_minutes": 10, "timeout_seconds": 15, "retry_count": 2, "backoff_strategy": "linear"},
                priority=0,
            ),
            # Case B: multi_zone -- one endpoint serving north wing rooms
            TelemetryEndpoint(
                endpoint_id="ep-multi-nw",
                building_id="bldg-demo",
                endpoint_name="BMS North Wing",
                endpoint_url="https://bms.demo.com/api/north/readings",
                authentication_config={"type": "bearer_token", "token": "demo-bearer-token"},
                endpoint_mode="multi_zone",
                served_zone_ids=["zone-hvac-nw"],
                served_room_ids=["loc-rm101", "loc-rm102", "loc-rm201"],
                available_metrics=["temperature", "co2", "relative_humidity"],
                response_format={
                    "readings_path": "data.measurements",
                    "fields": {
                        "metric_type": "$.type",
                        "value": "$.val",
                        "unit": "$.unit",
                        "recorded_at": "$.ts",
                        "zone_code": "$.zone_id",
                    },
                    "metric_type_map": {"temp": "temperature", "rh": "relative_humidity", "carbon_dioxide": "co2"},
                    "timestamp_format": "iso8601",
                },
                location_mapping={
                    "strategy": "field_match",
                    "source_field": "zone_code",
                    "match_target": "external_refs.bms_zone",
                },
                polling_config={"interval_minutes": 10, "timeout_seconds": 30, "retry_count": 3, "backoff_strategy": "exponential"},
                priority=0,
            ),
            # Case C: building_wide -- one endpoint for the entire building
            TelemetryEndpoint(
                endpoint_id="ep-building-wide",
                building_id="bldg-demo",
                endpoint_name="Central BMS All Data",
                endpoint_url="https://bms.demo.com/api/all",
                authentication_config={
                    "type": "oauth2_client_credentials",
                    "token_url": "https://bms.demo.com/oauth/token",
                    "client_id": "comfortos",
                    "client_secret": "demo-secret",
                },
                endpoint_mode="building_wide",
                available_metrics=["temperature", "co2", "relative_humidity", "noise"],
                response_format={
                    "readings_path": "data.all_readings",
                    "fields": {
                        "metric_type": "$.measurement_type",
                        "value": "$.measured_value",
                        "unit": "$.unit_of_measure",
                        "recorded_at": "$.capture_time",
                        "zone_code": "$.location_code",
                        "sensor_id": "$.device_id",
                    },
                    "metric_type_map": {
                        "AIR_TEMP": "temperature",
                        "CARBON_DIOXIDE": "co2",
                        "REL_HUMIDITY": "relative_humidity",
                        "SOUND_PRESSURE": "noise",
                    },
                    "unit_map": {"degC": "C", "PPM": "ppm", "PCT": "%", "dB(A)": "dBA"},
                    "timestamp_format": "iso8601",
                },
                location_mapping={
                    "strategy": "field_match",
                    "source_field": "zone_code",
                    "match_target": "external_refs.bms_zone",
                },
                sensor_mapping={
                    "source_field": "sensor_id",
                    "match_target": "source_identifier",
                    "auto_register": True,
                },
                polling_config={"interval_minutes": 5, "timeout_seconds": 60, "retry_count": 3, "backoff_strategy": "exponential"},
                priority=1,
            ),
            # Case D: multi_endpoint_multi_zone -- south wing endpoint
            TelemetryEndpoint(
                endpoint_id="ep-multi-sw",
                building_id="bldg-demo",
                endpoint_name="BMS South Wing",
                endpoint_url="https://bms.demo.com/api/south/readings",
                authentication_config={"type": "api_key", "header": "X-BMS-Key", "api_key": "demo-sw-key"},
                endpoint_mode="multi_zone",
                served_room_ids=["loc-rm-sw1"],
                available_metrics=["temperature", "relative_humidity"],
                response_format={
                    "readings_path": "readings",
                    "fields": {
                        "metric_type": "$.metric",
                        "value": "$.value",
                        "recorded_at": "$.timestamp",
                        "zone_code": "$.room_code",
                    },
                    "timestamp_format": "iso8601",
                },
                location_mapping={
                    "strategy": "field_match",
                    "source_field": "zone_code",
                    "match_target": "external_refs.bms_zone",
                },
                polling_config={"interval_minutes": 15, "timeout_seconds": 30, "retry_count": 2, "backoff_strategy": "linear"},
                priority=0,
            ),
            # Case E: sensor_centric -- raw sensor data from IoT gateway
            TelemetryEndpoint(
                endpoint_id="ep-sensor-iot",
                building_id="bldg-demo",
                endpoint_name="IoT Noise Sensors",
                endpoint_url="https://iot.demo.com/api/noise/latest",
                authentication_config={"type": "bearer_token", "token": "demo-iot-token"},
                endpoint_mode="sensor_centric",
                served_sensor_ids=["sens-noise-201"],
                available_metrics=["noise"],
                response_format={
                    "readings_path": "sensors",
                    "fields": {
                        "value": "$.db_level",
                        "recorded_at": "$.last_reading_at",
                        "sensor_id": "$.device_serial",
                    },
                },
                sensor_mapping={
                    "source_field": "sensor_id",
                    "match_target": "source_identifier",
                    "auto_register": False,
                },
                normalization_profile={
                    "default_source_level": "sensor",
                },
                polling_config={"interval_minutes": 5, "timeout_seconds": 15, "retry_count": 2, "backoff_strategy": "linear"},
                priority=0,
            ),
        ]
        db.add_all(endpoints)

        # ── Building Telemetry Config ────────────────────────────────
        configs = [
            BuildingTelemetryConfig(
                building_id="bldg-demo", metric_type="temperature",
                is_enabled=True, default_unit="C",
                source_level="sensor", room_aggregation_rule="avg",
                valid_range_min=-10, valid_range_max=50,
                stale_threshold_minutes=30,
                conflict_resolution="connector_priority",
                connector_priority=["ep-multi-nw", "ep-building-wide"],
            ),
            BuildingTelemetryConfig(
                building_id="bldg-demo", metric_type="co2",
                is_enabled=True, default_unit="ppm",
                source_level="sensor", room_aggregation_rule="avg",
                valid_range_min=300, valid_range_max=5000,
                stale_threshold_minutes=15,
                conflict_resolution="newest_wins",
            ),
            BuildingTelemetryConfig(
                building_id="bldg-demo", metric_type="relative_humidity",
                is_enabled=True, default_unit="%",
                source_level="sensor", room_aggregation_rule="avg",
                valid_range_min=0, valid_range_max=100,
                stale_threshold_minutes=30,
                conflict_resolution="newest_wins",
            ),
            BuildingTelemetryConfig(
                building_id="bldg-demo", metric_type="noise",
                is_enabled=True, default_unit="dBA",
                source_level="room", room_aggregation_rule="max",
                valid_range_min=20, valid_range_max=120,
                stale_threshold_minutes=60,
                conflict_resolution="newest_wins",
            ),
        ]
        db.add_all(configs)

        # ── Example telemetry readings ───────────────────────────────
        now = datetime.now(timezone.utc)
        readings = [
            # Room 1.01 -- two temp sensors, one CO2, one RH
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm101",
                sensor_id="sens-t1-win", metric_type="temperature",
                value=22.1, unit="C", recorded_at=now - timedelta(minutes=5),
                source_level="sensor", quality_flag="good",
                connector_id="ep-multi-nw"),
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm101",
                sensor_id="sens-t1-cor", metric_type="temperature",
                value=22.5, unit="C", recorded_at=now - timedelta(minutes=5),
                source_level="sensor", quality_flag="good",
                connector_id="ep-multi-nw"),
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm101",
                sensor_id="sens-co2-101", metric_type="co2",
                value=680, unit="ppm", recorded_at=now - timedelta(minutes=5),
                source_level="sensor", quality_flag="good",
                connector_id="ep-multi-nw"),
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm101",
                sensor_id="sens-co2-101", metric_type="relative_humidity",
                value=45.2, unit="%", recorded_at=now - timedelta(minutes=5),
                source_level="sensor", quality_flag="good",
                connector_id="ep-multi-nw"),
            # Room 1.02 -- all four metrics from multi-sensor
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm102",
                sensor_id="sens-multi-102", metric_type="temperature",
                value=21.8, unit="C", recorded_at=now - timedelta(minutes=3),
                source_level="sensor", quality_flag="good"),
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm102",
                sensor_id="sens-multi-102", metric_type="co2",
                value=720, unit="ppm", recorded_at=now - timedelta(minutes=3),
                source_level="sensor", quality_flag="good"),
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm102",
                sensor_id="sens-multi-102", metric_type="relative_humidity",
                value=48.1, unit="%", recorded_at=now - timedelta(minutes=3),
                source_level="sensor", quality_flag="good"),
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm102",
                sensor_id="sens-multi-102", metric_type="noise",
                value=42.7, unit="dBA", recorded_at=now - timedelta(minutes=3),
                source_level="sensor", quality_flag="good"),
            # Room 2.01 -- temp at placement + noise at room
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm201",
                sensor_id="sens-t-201", metric_type="temperature",
                value=23.0, unit="C", recorded_at=now - timedelta(minutes=2),
                source_level="sensor", quality_flag="good"),
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm201",
                sensor_id="sens-noise-201", metric_type="noise",
                value=38.5, unit="dBA", recorded_at=now - timedelta(minutes=2),
                source_level="sensor", quality_flag="good",
                connector_id="ep-sensor-iot"),
            # Room S1.01 -- south wing
            TelemetryReading(
                building_id="bldg-demo", location_id="loc-rm-sw1",
                sensor_id="sens-t-sw101", metric_type="temperature",
                value=20.9, unit="C", recorded_at=now - timedelta(minutes=10),
                source_level="sensor", quality_flag="good",
                connector_id="ep-multi-sw"),
        ]
        db.add_all(readings)

        await db.commit()
        print("Telemetry seed data created successfully.")
        print(f"  Building: bldg-demo")
        print(f"  Locations: {len(locations)}")
        print(f"  Sensors: {len(sensors)}")
        print(f"  Zones: {len(zones)}")
        print(f"  Endpoints: {len(endpoints)}")
        print(f"  Metric configs: {len(configs)}")
        print(f"  Sample readings: {len(readings)}")


if __name__ == "__main__":
    asyncio.run(seed())
