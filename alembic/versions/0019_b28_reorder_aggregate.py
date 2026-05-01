"""Reorder Building 28 dashboard and replace static comfort bars.

Changes from the layout written by 0017:
  1. "Compare floors — temperature" chart moves above the comfort
     section (previously below it).
  2. The "How does it feel?" header is renamed to "How are people
     feeling in the office over the last week?".
  3. Static `progress_bar` widgets are replaced with a single
     `vote_aggregate` node that fetches the last 7 days of comfort
     votes and shows real averages for thermal / air / acoustic.

Revision ID: 0019_b28_reorder_aggregate
Revises: 0018_shift_hhs_into_may_2026
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "0019_b28_reorder_aggregate"
down_revision = "0018_shift_hhs_into_may_2026"
branch_labels = None
depends_on = None


B28_BUILDING_ID = "bldg-28"


B28_DASHBOARD = {
    "type": "column",
    "crossAxisAlignment": "stretch",
    "children": [
        {
            "type": "image_banner",
            "title": "Welcome to Building 28",
            "subtitle": "Your meeting room is set up and ready",
            "color": "teal",
        },
        {"type": "spacer", "height": 12},
        {
            "type": "weather_badge",
            "temp": "14", "unit": "°C",
            "label": "The Hague — sunny", "icon": "wb_sunny",
        },
        {"type": "spacer", "height": 12},
        {"type": "room_selector", "room": "Meeting Room 4.E.040 — East Wing"},
        {"type": "spacer", "height": 16},
        {"type": "section_header", "title": "This room — live", "icon": "thermostat"},
        {"type": "spacer", "height": 8},
        {
            "type": "gauge",
            "label": "Temperature",
            "value": 21.4, "min": 16, "max": 28, "unit": "°C",
            "color": "teal",
            "bands": [
                {"from": 16, "to": 19, "color": "blue"},
                {"from": 19, "to": 24, "color": "green"},
                {"from": 24, "to": 28, "color": "red"},
            ],
        },
        {"type": "spacer", "height": 24},
        {"type": "section_header", "title": "Compare floors — temperature", "icon": "apartment"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "temperature",
            "title": "Temperature by floor",
            "unit": "°C",
            "height": 260,
            "chartKind": "line",
            "mode": "floor",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last 6 hours",  "hours": 6,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
                {"label": "Last 7 days",   "hours": 168, "granularity": "hourly"},
            ],
        },
        {"type": "spacer", "height": 24},
        {
            "type": "section_header",
            "title": "How are people feeling in the office over the last week?",
            "icon": "favorite",
        },
        {"type": "spacer", "height": 8},
        {
            "type": "vote_aggregate",
            "windowDays": 7,
            "metrics": [
                {"id": "thermal_comfort", "label": "Thermal comfort",  "color": "teal",  "kind": "thermal"},
                {"id": "air_quality",     "label": "Air freshness",    "color": "amber", "kind": "air"},
                {"id": "noise_level",     "label": "Acoustic quality", "color": "teal",  "kind": "noise"},
            ],
        },
        {"type": "spacer", "height": 24},
        {"type": "section_header", "title": "Compare wings — temperature", "icon": "business"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "temperature",
            "title": "Temperature: East vs West",
            "unit": "°C",
            "height": 260,
            "chartKind": "line",
            "mode": "wing",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last 6 hours",  "hours": 6,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
                {"label": "Last 7 days",   "hours": 168, "granularity": "hourly"},
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
    merged = dict(B28_DASHBOARD)
    existing_key = _existing_api_key(conn, B28_BUILDING_ID)
    if existing_key:
        merged["telemetryApiKey"] = existing_key
    _write_layout(conn, B28_BUILDING_ID, merged)


def downgrade() -> None:
    """No-op: layout from 0017 stays in place."""
    pass
