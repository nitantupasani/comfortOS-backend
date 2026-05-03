"""Shift HHS comfort votes forward to match the telemetry shift in 0018.

Migration 0018 advanced HHS ``telemetry_readings`` by an integer number
of weeks so the chart windows had data once the wall clock crossed into
May 2026. The ``votes`` rows for the same building were not shifted, so
vote-aggregate panels now sit out of range relative to the telemetry.

This migration applies the same week-aligned shift to ``votes`` rows
for the HHS building, using the same target and formula as 0018:
shift forward by the smallest integer number of weeks such that
MAX(created_at) lands at or after 2026-05-31 23:00 UTC. Week alignment
preserves weekday (matching the convention of 0007/0018). No-op if the
data already extends past the target.

Revision ID: 0024_shift_hhs_votes_into_may_2026
Revises: 0023_b28_minimal_vote_form
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_shift_hhs_votes_into_may_2026"
down_revision = "0023_b28_minimal_vote_form"
branch_labels = None
depends_on = None

BUILDING_ID = "bldg-5e32215a"
TARGET_MAX = "2026-05-31 23:00:00+00"


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("SET statement_timeout = 0"))

    weeks_row = conn.execute(sa.text(f"""
        SELECT GREATEST(
            0,
            CEIL(
                EXTRACT(EPOCH FROM (TIMESTAMPTZ '{TARGET_MAX}' - MAX(created_at)))
                / (7 * 86400)
            )::int
        )
        FROM votes
        WHERE building_id = :bid
    """).bindparams(bid=BUILDING_ID)).first()

    weeks = int(weeks_row[0]) if weeks_row and weeks_row[0] is not None else 0
    if weeks <= 0:
        return

    conn.execute(sa.text(f"""
        UPDATE votes
        SET created_at = created_at + INTERVAL '{weeks * 7} days'
        WHERE building_id = :bid
    """).bindparams(bid=BUILDING_ID))


def downgrade() -> None:
    """No-op: forward data shift is not exactly reversible after further ingest."""
    pass
