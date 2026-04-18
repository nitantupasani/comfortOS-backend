"""Create Location records for Building 28 rooms and backfill location_id.

Each room folder follows the pattern {floor}-{wing}-{room}, e.g. '1-W-560'.
This migration creates a location hierarchy (building → floor → room) and
updates existing telemetry_readings to link to the correct location_id
by matching on the zone column.

Revision ID: 0010_building28_locations
Revises: 0009_telemetry_integration
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_building28_locations"
down_revision = "0009_telemetry_integration"
branch_labels = None
depends_on = None

BUILDING_ID = "bldg-28"

# All room folders from the dataset
ROOMS = [
    "1-W-560", "1-W-780", "1-W-880",
    "2-E-040", "2-E-340", "2-E-420", "2-W-760",
    "3-E-240",
    "4-E-040", "4-E-100", "4-W-820",
    "5-E-280", "5-W-920",
    "6-W-720", "6-W-920",
]


def _parse_room(code: str):
    """Parse '1-W-560' → (floor='1', wing='W', room='560')."""
    parts = code.split("-")
    return parts[0], parts[1], parts[2]


def upgrade() -> None:
    conn = op.get_bind()

    # Collect unique floors
    floors = sorted(set(_parse_room(r)[0] for r in ROOMS))

    # Create floor-level locations
    for floor in floors:
        floor_id = f"loc-b28-F{floor}"
        conn.execute(sa.text(
            "INSERT INTO locations (id, building_id, parent_id, type, name, code, sort_order) "
            "VALUES (:id, :bid, NULL, 'floor', :name, :code, :sort) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=floor_id, bid=BUILDING_ID,
            name=f"Floor {floor}", code=f"F{floor}", sort=int(floor),
        ))

    # Create room-level locations and backfill telemetry_readings
    for room_code in ROOMS:
        floor, wing, room = _parse_room(room_code)
        floor_id = f"loc-b28-F{floor}"
        room_id = f"loc-b28-{room_code}"
        wing_name = "West" if wing == "W" else "East"
        room_name = f"{floor}.{wing}.{room}"

        conn.execute(sa.text(
            "INSERT INTO locations (id, building_id, parent_id, type, name, code, sort_order) "
            "VALUES (:id, :bid, :pid, 'room', :name, :code, :sort) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=room_id, bid=BUILDING_ID, pid=floor_id,
            name=room_name, code=room_code, sort=int(room),
        ))

        # Backfill: set location_id on telemetry_readings that match this zone
        conn.execute(sa.text(
            "UPDATE telemetry_readings "
            "SET location_id = :loc_id "
            "WHERE building_id = :bid AND zone = :zone AND location_id IS NULL"
        ).bindparams(loc_id=room_id, bid=BUILDING_ID, zone=room_code))


def downgrade() -> None:
    conn = op.get_bind()
    # Clear location_id from telemetry_readings
    conn.execute(sa.text(
        "UPDATE telemetry_readings SET location_id = NULL "
        "WHERE building_id = :bid AND location_id LIKE 'loc-b28-%'"
    ).bindparams(bid=BUILDING_ID))
    # Delete room locations, then floor locations
    conn.execute(sa.text(
        "DELETE FROM locations WHERE building_id = :bid AND type = 'room'"
    ).bindparams(bid=BUILDING_ID))
    conn.execute(sa.text(
        "DELETE FROM locations WHERE building_id = :bid AND type = 'floor'"
    ).bindparams(bid=BUILDING_ID))
