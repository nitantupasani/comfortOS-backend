"""Create Location records for HHS building zones and backfill location_id.

Zone codes follow the pattern ST{NN} (e.g. ST01, ST10), derived from
RAWST*.xlsx filenames. Floor is always '0'. This migration creates a
location hierarchy (building → room) and updates existing telemetry_readings
to link to the correct location_id by matching on the zone column.

Revision ID: 0011_hhs_locations
Revises: 0010_building28_locations
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_hhs_locations"
down_revision = "0010_building28_locations"
branch_labels = None
depends_on = None

BUILDING_ID = "bldg-5e32215a"

# Zone codes and their human-readable labels from equipdis
# Format: (zone_code, display_name)
ZONES = [
    ("ST01", "Strip 0.01"),
    ("ST02", "Strip 0.02"),
    ("ST03", "Strip 0.03"),
    ("ST04", "Strip 0.04"),
    ("ST05", "Strip 0.05"),
    ("ST06", "Strip 0.06"),
    ("ST07", "Strip 0.07"),
    ("ST08", "Strip 0.08"),
    ("ST09", "Strip 0.09"),
    ("ST10", "Strip 0.10"),
    ("ST11", "Strip 0.11"),
    ("ST12", "Strip 0.12"),
    ("ST13", "Strip 0.13"),
    ("ST14", "Strip 0.14"),
    ("ST15", "Strip 0.15"),
    ("ST16", "Strip 0.16"),
    ("ST17", "Strip 0.17"),
    ("ST18", "Strip 0.18"),
    ("ST19", "Strip 0.19"),
    ("ST20", "Strip 0.20"),
    ("ST21", "Strip 0.21"),
    ("ST22", "Strip 0.22"),
    ("ST23", "Strip 0.23"),
    ("ST24", "Strip 0.24"),
    ("ST25", "Strip 0.25"),
    ("ST26", "Strip 0.26"),
    ("ST27", "Strip 0.27"),
    ("ST28", "Strip 0.28"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Find which zones actually have telemetry data
    result = conn.execute(sa.text(
        "SELECT DISTINCT zone FROM telemetry_readings "
        "WHERE building_id = :bid AND zone IS NOT NULL"
    ).bindparams(bid=BUILDING_ID))
    existing_zones = {row[0] for row in result}

    # Create room-level locations for each zone that has data
    for zone_code, display_name in ZONES:
        if zone_code not in existing_zones:
            continue

        loc_id = f"loc-hhs-{zone_code}"
        conn.execute(sa.text(
            "INSERT INTO locations (id, building_id, parent_id, type, name, code, sort_order, external_refs, created_at, updated_at) "
            "VALUES (:id, :bid, NULL, 'room', :name, :code, :sort, CAST(:refs AS json), NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=loc_id, bid=BUILDING_ID,
            name=display_name, code=zone_code,
            sort=int(zone_code[2:]),
            refs=f'{{"bms_zone": "{zone_code}"}}',
        ))

        # Backfill: set location_id on telemetry_readings that match this zone
        conn.execute(sa.text(
            "UPDATE telemetry_readings "
            "SET location_id = :loc_id "
            "WHERE building_id = :bid AND zone = :zone AND location_id IS NULL"
        ).bindparams(loc_id=loc_id, bid=BUILDING_ID, zone=zone_code))


def downgrade() -> None:
    conn = op.get_bind()
    # Clear location_id from telemetry_readings
    conn.execute(sa.text(
        "UPDATE telemetry_readings SET location_id = NULL "
        "WHERE building_id = :bid AND location_id LIKE 'loc-hhs-%'"
    ).bindparams(bid=BUILDING_ID))
    # Delete locations
    conn.execute(sa.text(
        "DELETE FROM locations WHERE building_id = :bid"
    ).bindparams(bid=BUILDING_ID))
