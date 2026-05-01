"""Shift HHS telemetry forward so data covers May 2026.

The HHS dataset originally extended only through ~mid-April 2026, so the
default chart windows (last 6 hours / 24 hours / 7 days) returned no
data once the wall clock crossed into May 2026.

This migration shifts every HHS telemetry_readings row forward by an
integer number of WEEKS (preserves weekday alignment, matching the
convention of migration 0007). The shift is computed dynamically so
that the new MAX(recorded_at) lands at or after 2026-05-31 23:00 UTC.
If the data is already past that target, the migration is a no-op.

Revision ID: 0018_shift_hhs_into_may_2026
Revises: 0017_b28_temperature_only
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_shift_hhs_into_may_2026"
down_revision = "0017_b28_temperature_only"
branch_labels = None
depends_on = None

BUILDING_ID = "bldg-5e32215a"
TARGET_MAX = "2026-05-31 23:00:00+00"


def upgrade() -> None:
    conn = op.get_bind()

    # Supabase imposes a per-statement timeout; disable it for this bulk
    # UPDATE so the full HHS reading set can shift in one pass.
    conn.execute(sa.text("SET statement_timeout = 0"))

    # Integer number of weeks to shift so MAX(recorded_at) >= TARGET_MAX.
    # GREATEST(0, ...) means we never shift backwards.
    weeks_row = conn.execute(sa.text(f"""
        SELECT GREATEST(
            0,
            CEIL(
                EXTRACT(EPOCH FROM (TIMESTAMPTZ '{TARGET_MAX}' - MAX(recorded_at)))
                / (7 * 86400)
            )::int
        )
        FROM telemetry_readings
        WHERE building_id = :bid
    """).bindparams(bid=BUILDING_ID)).first()

    weeks = int(weeks_row[0]) if weeks_row and weeks_row[0] is not None else 0
    if weeks <= 0:
        return

    conn.execute(sa.text(f"""
        UPDATE telemetry_readings
        SET recorded_at = recorded_at + INTERVAL '{weeks * 7} days'
        WHERE building_id = :bid
    """).bindparams(bid=BUILDING_ID))


def downgrade() -> None:
    """No-op: forward data shift is not exactly reversible after further ingest."""
    pass
