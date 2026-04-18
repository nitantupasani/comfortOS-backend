"""Restructure Building 28 hierarchy to Wing -> Floor -> Room.

Migration 0010 created a flat Floor -> Room hierarchy. Each room code
follows {floor}-{wing}-{room} (e.g. '1-W-560'), so wings are implicit
in the data. This migration promotes wings to first-class nodes:

    Before: Floor 1 -> 1.W.560
    After:  West Wing -> Floor 1 -> 1.W.560

Floors that contain rooms from both wings (e.g. Floor 2 has 2.W.760
and 2.E.*) get split into two floor nodes, one per wing, since each
wing is a physically distinct section of the building.

Room IDs are unchanged, so telemetry_readings.location_id remains valid.

Revision ID: 0012_building28_wings
Revises: 0011_hhs_locations
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_building28_wings"
down_revision = "0011_hhs_locations"
branch_labels = None
depends_on = None

BUILDING_ID = "bldg-28"

ROOMS = [
    "1-W-560", "1-W-780", "1-W-880",
    "2-E-040", "2-E-340", "2-E-420", "2-W-760",
    "3-E-240",
    "4-E-040", "4-E-100", "4-W-820",
    "5-E-280", "5-W-920",
    "6-W-720", "6-W-920",
]

WINGS = {
    "W": ("loc-b28-wing-W", "West Wing", "west", 1),
    "E": ("loc-b28-wing-E", "East Wing", "east", 2),
}


def _parse_room(code: str):
    parts = code.split("-")
    return parts[0], parts[1], parts[2]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("SET statement_timeout = 0"))

    # 1. Create wing nodes (parent=NULL, so they sit at the top of the tree)
    for wing_letter, (wing_id, wing_name, orientation, sort) in WINGS.items():
        conn.execute(sa.text(
            "INSERT INTO locations (id, building_id, parent_id, type, name, code, orientation, sort_order, created_at, updated_at) "
            "VALUES (:id, :bid, NULL, 'block_or_wing', :name, :code, :orient, :sort, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=wing_id, bid=BUILDING_ID,
            name=wing_name, code=f"W-{wing_letter}",
            orient=orientation, sort=sort,
        ))

    # 2. Create per-wing floor nodes for each (floor, wing) pair actually present.
    floor_wing_pairs = sorted({(_parse_room(r)[0], _parse_room(r)[1]) for r in ROOMS})
    for floor, wing_letter in floor_wing_pairs:
        wing_id = WINGS[wing_letter][0]
        new_floor_id = f"loc-b28-{wing_letter}-F{floor}"
        conn.execute(sa.text(
            "INSERT INTO locations (id, building_id, parent_id, type, name, code, sort_order, created_at, updated_at) "
            "VALUES (:id, :bid, :pid, 'floor', :name, :code, :sort, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=new_floor_id, bid=BUILDING_ID, pid=wing_id,
            name=f"Floor {floor}", code=f"F{floor}", sort=int(floor),
        ))

    # 3. Re-parent each room to its new (wing, floor) node.
    for room_code in ROOMS:
        floor, wing_letter, _ = _parse_room(room_code)
        room_id = f"loc-b28-{room_code}"
        new_floor_id = f"loc-b28-{wing_letter}-F{floor}"
        conn.execute(sa.text(
            "UPDATE locations SET parent_id = :pid, updated_at = NOW() "
            "WHERE id = :id"
        ).bindparams(id=room_id, pid=new_floor_id))

    # 4. Remove the old floor nodes (loc-b28-F1 .. loc-b28-F6), now childless.
    conn.execute(sa.text(
        "DELETE FROM locations "
        "WHERE building_id = :bid AND type = 'floor' "
        "  AND parent_id IS NULL AND id LIKE 'loc-b28-F%'"
    ).bindparams(bid=BUILDING_ID))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("SET statement_timeout = 0"))

    # 1. Recreate the flat floor nodes from migration 0010.
    floors = sorted(set(_parse_room(r)[0] for r in ROOMS))
    for floor in floors:
        floor_id = f"loc-b28-F{floor}"
        conn.execute(sa.text(
            "INSERT INTO locations (id, building_id, parent_id, type, name, code, sort_order, created_at, updated_at) "
            "VALUES (:id, :bid, NULL, 'floor', :name, :code, :sort, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=floor_id, bid=BUILDING_ID,
            name=f"Floor {floor}", code=f"F{floor}", sort=int(floor),
        ))

    # 2. Re-parent rooms back to the flat floor nodes.
    for room_code in ROOMS:
        floor, _, _ = _parse_room(room_code)
        conn.execute(sa.text(
            "UPDATE locations SET parent_id = :pid, updated_at = NOW() "
            "WHERE id = :id"
        ).bindparams(id=f"loc-b28-{room_code}", pid=f"loc-b28-F{floor}"))

    # 3. Delete the wing-scoped floor nodes and the wings.
    conn.execute(sa.text(
        "DELETE FROM locations "
        "WHERE building_id = :bid AND type = 'floor' AND id LIKE 'loc-b28-%-F%'"
    ).bindparams(bid=BUILDING_ID))
    conn.execute(sa.text(
        "DELETE FROM locations "
        "WHERE building_id = :bid AND type = 'block_or_wing' AND id LIKE 'loc-b28-wing-%'"
    ).bindparams(bid=BUILDING_ID))
