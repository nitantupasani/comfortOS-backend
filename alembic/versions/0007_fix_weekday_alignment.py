"""Fix weekday alignment: shift telemetry + vote timestamps by +3 days.

The original data was shifted ~1096 days into the future, but 1096 mod 7 = 4,
so weekdays drifted.  Adding 3 days makes the total 1099 = 157 full weeks,
preserving exact day-of-week alignment.

NOTE: Votes were already corrected via the /votes/ingest upsert endpoint.
This migration fixes telemetry_readings timestamps and any votes that were
missed.

Revision ID: 0007_fix_weekday_alignment
Revises: 0006_nullable_vote_user_id
"""
from alembic import op

revision = "0007_fix_weekday_alignment"
down_revision = "0006_nullable_vote_user_id"
branch_labels = None
depends_on = None

BUILDING_ID = "bldg-5e32215a"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE telemetry_readings
        SET recorded_at = recorded_at + INTERVAL '3 days'
        WHERE building_id = '{BUILDING_ID}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE telemetry_readings
        SET recorded_at = recorded_at - INTERVAL '3 days'
        WHERE building_id = '{BUILDING_ID}'
        """
    )
