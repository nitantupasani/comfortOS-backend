"""Re-apply HHS / Building 28 dashboard layouts.

Migration 0015 has already run on deployed environments, so subsequent
edits to its embedded layout JSON are not picked up automatically.
This migration re-writes the active dashboard_layout for both buildings
to the current target shape:

  - HHS (bldg-5e32215a): flat-room office. KPI grid, two `pick`-mode
    telemetry charts (temperature line, CO₂ area), hottest-rooms bar
    list, CO₂ alert. No floor/wing/strip-count badges, no heatmap.

  - Building 28 (bldg-28): typical office. Twin gauges, comfort
    progress bars, four locked telemetry charts comparing floors and
    wings (temperature + CO₂). No schedule items, no `primary_action`
    (the occupant Dashboard already renders a hard-coded vote button
    below the SDUI tree, so an in-tree action doubles up).

Any pre-existing telemetryApiKey on the active config is preserved.

Revision ID: 0016_refresh_dashboards
Revises: 0015_distinct_dashboards
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "0016_refresh_dashboards"
down_revision = "0015_distinct_dashboards"
branch_labels = None
depends_on = None


HHS_BUILDING_ID = "bldg-5e32215a"
B28_BUILDING_ID = "bldg-28"


HHS_HOTTEST = [
    {"label": "ST14", "value": 25.1, "color": "red"},
    {"label": "ST07", "value": 24.6, "color": "orange"},
    {"label": "ST15", "value": 24.4, "color": "orange"},
    {"label": "ST05", "value": 23.8, "color": "amber"},
    {"label": "ST26", "value": 23.7, "color": "amber"},
]


HHS_DASHBOARD = {
    "type": "column",
    "crossAxisAlignment": "stretch",
    "children": [
        {
            "type": "image_banner",
            "title": "HHS office",
            "subtitle": "University open-plan workspace",
            "color": "indigo",
        },
        {"type": "spacer", "height": 12},
        {
            "type": "weather_badge",
            "temp": "13", "unit": "°C",
            "label": "The Hague", "icon": "cloud",
        },
        {"type": "spacer", "height": 16},
        {"type": "section_header", "title": "Office at a glance", "icon": "monitor_heart"},
        {"type": "spacer", "height": 8},
        {
            "type": "grid",
            "columns": 2,
            "spacing": 10,
            "children": [
                {"type": "kpi_card", "label": "Avg temperature", "value": "22.7", "unit": "°C",  "trend": "up"},
                {"type": "kpi_card", "label": "Avg CO₂",         "value": "612",  "unit": "ppm", "trend": "down"},
                {"type": "kpi_card", "label": "Rooms occupied",  "value": "19",   "unit": "/ 28","trend": "up"},
                {"type": "kpi_card", "label": "Comfort score",   "value": "78",   "unit": "%",   "trend": "up"},
            ],
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Pick a room — temperature", "icon": "thermostat"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "temperature",
            "title": "Temperature",
            "unit": "°C",
            "height": 260,
            "chartKind": "line",
            "mode": "pick",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last 6 hours",  "hours": 6,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
                {"label": "Last 7 days",   "hours": 168, "granularity": "hourly"},
            ],
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Pick a room — CO₂", "icon": "co2"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "co2",
            "title": "CO₂",
            "unit": "ppm",
            "height": 260,
            "chartKind": "area",
            "mode": "pick",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last hour",     "hours": 1,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
                {"label": "Last 7 days",   "hours": 168, "granularity": "hourly"},
            ],
        },
        {"type": "spacer", "height": 20},
        {
            "type": "bar_list",
            "title": "Hottest rooms right now",
            "unit": "°C",
            "items": HHS_HOTTEST,
        },
        {"type": "spacer", "height": 16},
        {
            "type": "alert_banner",
            "icon": "warning",
            "title": "Sustained CO₂ above 900 ppm — Strip 0.14",
            "subtitle": "Detected for 22 min · ventilation set-point auto-raised.",
            "color": "amber",
        },
    ],
}


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
            "type": "grid",
            "columns": 2,
            "spacing": 10,
            "children": [
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
                {
                    "type": "gauge",
                    "label": "CO₂",
                    "value": 742, "min": 400, "max": 1500, "unit": "ppm",
                    "color": "amber",
                    "bands": [
                        {"from": 400,  "to": 800,  "color": "green"},
                        {"from": 800,  "to": 1200, "color": "amber"},
                        {"from": 1200, "to": 1500, "color": "red"},
                    ],
                },
            ],
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "How does it feel?", "icon": "favorite"},
        {"type": "spacer", "height": 8},
        {"type": "progress_bar", "label": "Thermal comfort", "value": 82, "color": "teal"},
        {"type": "progress_bar", "label": "Air freshness",   "value": 64, "color": "amber"},
        {"type": "progress_bar", "label": "Acoustic quality","value": 90, "color": "teal"},
        {"type": "spacer", "height": 24},
        {"type": "section_header", "title": "Compare floors — temperature", "icon": "apartment"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "temperature",
            "title": "Temperature by floor",
            "unit": "°C",
            "height": 240,
            "chartKind": "line",
            "mode": "floor",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last 6 hours",  "hours": 6,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
                {"label": "Last 7 days",   "hours": 168, "granularity": "hourly"},
            ],
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Compare floors — CO₂", "icon": "co2"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "co2",
            "title": "CO₂ by floor",
            "unit": "ppm",
            "height": 240,
            "chartKind": "area",
            "mode": "floor",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last hour",     "hours": 1,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
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
            "height": 240,
            "chartKind": "line",
            "mode": "wing",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last 6 hours",  "hours": 6,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
                {"label": "Last 7 days",   "hours": 168, "granularity": "hourly"},
            ],
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Compare wings — CO₂", "icon": "co2"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "co2",
            "title": "CO₂: East vs West (latest)",
            "unit": "ppm",
            "height": 220,
            "chartKind": "bar",
            "mode": "wing",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last hour",     "hours": 1,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
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
    for bid, layout in (
        (HHS_BUILDING_ID, HHS_DASHBOARD),
        (B28_BUILDING_ID, B28_DASHBOARD),
    ):
        merged = dict(layout)
        existing_key = _existing_api_key(conn, bid)
        if existing_key:
            merged["telemetryApiKey"] = existing_key
        _write_layout(conn, bid, merged)


def downgrade() -> None:
    """No-op: layout from 0015 stays in place."""
    pass
