"""Sirius Den Haag dashboard: temperature-only with live tile + chart.

Trims the occupant dashboard for Sirius Den Haag (Fluwelen Burgwal 58, Priva
Cloud) to temperature only: drops the CO₂, noise, and relative-humidity tiles,
keeps a live per-room temperature tile, and adds a Building-28-style
temperature line chart defaulting to the last 6 hours with a 12-hour option.

Revision ID: 0025_sirius_temperature_only
Revises: 0024_shift_hhs_votes_may_2026
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "0025_sirius_temperature_only"
down_revision = "0024_shift_hhs_votes_may_2026"
branch_labels = None
depends_on = None


SIRIUS_BUILDING_ID = "bldg-8f2fd3cf"


SIRIUS_DASHBOARD = {
    "type": "column",
    "crossAxisAlignment": "stretch",
    "children": [
        {
            "type": "weather_badge",
            "temp": "--", "unit": "°C",
            "label": "Outside", "icon": "wb_sunny",
        },
        {"type": "spacer", "height": 12},
        {"type": "section_header", "title": "This room — live", "icon": "thermostat"},
        {"type": "spacer", "height": 8},
        {
            "type": "metric_tile",
            "icon": "thermostat",
            "metricType": "temperature",
            "value": "--",
            "unit": "°C",
            "label": "Temperature",
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Temperature — recent", "icon": "thermostat"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "temperature",
            "title": "Temperature",
            "unit": "°C",
            "height": 260,
            "chartKind": "line",
            "timeRanges": [
                {"label": "Last 6 hours",  "hours": 6,  "granularity": "raw"},
                {"label": "Last 12 hours", "hours": 12, "granularity": "hourly"},
            ],
        },
    ],
}


def _existing_api_key(conn, building_id: str) -> str | None:
    row = conn.execute(
        sa.text(
            "SELECT dashboard_layout FROM building_configs "
            "WHERE building_id = :bid AND is_active = true "
            "ORDER BY created_at DESC LIMIT 1"
        ).bindparams(bid=building_id)
    ).first()
    if row is None or row[0] is None:
        return None
    layout = row[0]
    if isinstance(layout, str):
        try:
            layout = json.loads(layout)
        except (TypeError, ValueError):
            return None
    if isinstance(layout, dict):
        key = layout.get("telemetryApiKey")
        return key if isinstance(key, str) and key else None
    return None


def _write_layout(conn, building_id: str, layout: dict) -> None:
    payload = json.dumps(layout)
    result = conn.execute(
        sa.text(
            "UPDATE building_configs SET "
            "  dashboard_layout = CAST(:layout AS jsonb), "
            "  updated_at = NOW() "
            "WHERE id = ("
            "  SELECT id FROM building_configs "
            "  WHERE building_id = :bid AND is_active = true "
            "  ORDER BY created_at DESC LIMIT 1"
            ")"
        ).bindparams(layout=payload, bid=building_id)
    )
    if result.rowcount == 0:
        conn.execute(
            sa.text(
                "INSERT INTO building_configs "
                "  (id, building_id, schema_version, dashboard_layout, is_active, created_at, updated_at) "
                "VALUES "
                "  (:id, :bid, 1, CAST(:layout AS jsonb), true, NOW(), NOW())"
            ).bindparams(
                id=f"cfg-{building_id[-8:]}",
                bid=building_id,
                layout=payload,
            )
        )


def upgrade() -> None:
    conn = op.get_bind()
    merged = dict(SIRIUS_DASHBOARD)
    existing_key = _existing_api_key(conn, SIRIUS_BUILDING_ID)
    if existing_key:
        merged["telemetryApiKey"] = existing_key
    _write_layout(conn, SIRIUS_BUILDING_ID, merged)


def downgrade() -> None:
    """No-op: previous layout is not restored."""
    pass
