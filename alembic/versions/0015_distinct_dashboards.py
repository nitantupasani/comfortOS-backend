"""Set distinct SDUI dashboard layouts for HHS and Building 28.

Until now both buildings effectively rendered the same default dashboard,
which hid the diversity ComfortOS server-driven UI is meant to demonstrate.

This migration writes two purpose-built layouts that exercise different
SDUI primitives, chart types, and overall UX shapes:

  - HHS (bldg-5e32215a) — university open-plan office, 28 strips on a
    single floor. Operations / control-center feel: KPI grid, a
    floor-wide temperature heatmap, an AREA telemetry chart for
    temperature trends, a BAR telemetry chart for live CO₂ ranking,
    a static hottest-strips bar list, and a CO₂ alert banner.

  - Building 28 (bldg-28) — typical university office building with
    individual offices and meeting rooms. Occupant / room-booking feel:
    radial gauges (temperature, CO₂), comfort progress bars, a meeting
    room availability bar list, today's schedule, HVAC mode badges,
    and a comfort-vote primary action.

Any pre-existing telemetryApiKey on the active config is preserved.

Revision ID: 0015_distinct_dashboards
Revises: 0014_chat_sessions
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "0015_distinct_dashboards"
down_revision = "0014_chat_sessions"
branch_labels = None
depends_on = None


HHS_BUILDING_ID = "bldg-5e32215a"
B28_BUILDING_ID = "bldg-28"


# ── Demo data for static SDUI widgets ────────────────────────────────
# These values are illustrative — the live charts pull real telemetry.

HHS_HEATMAP_CELLS = [
    {"label": "ST01", "value": 21.4}, {"label": "ST02", "value": 22.0},
    {"label": "ST03", "value": 22.6}, {"label": "ST04", "value": 23.1},
    {"label": "ST05", "value": 23.8}, {"label": "ST06", "value": 24.2},
    {"label": "ST07", "value": 24.6}, {"label": "ST08", "value": 23.9},
    {"label": "ST09", "value": 23.2}, {"label": "ST10", "value": 22.7},
    {"label": "ST11", "value": 22.3}, {"label": "ST12", "value": 21.9},
    {"label": "ST13", "value": 21.6}, {"label": "ST14", "value": 25.1},
    {"label": "ST15", "value": 24.4}, {"label": "ST16", "value": 23.3},
    {"label": "ST17", "value": 22.8}, {"label": "ST18", "value": 22.1},
    {"label": "ST19", "value": 21.5}, {"label": "ST20", "value": 21.2},
    {"label": "ST21", "value": 21.0}, {"label": "ST22", "value": 20.8},
    {"label": "ST23", "value": 21.4}, {"label": "ST24", "value": 22.2},
    {"label": "ST25", "value": 23.0}, {"label": "ST26", "value": 23.7},
    {"label": "ST27", "value": 24.0}, {"label": "ST28", "value": 22.5},
]

HHS_HOTTEST = [
    {"label": "ST14", "value": 25.1, "color": "red"},
    {"label": "ST07", "value": 24.6, "color": "orange"},
    {"label": "ST15", "value": 24.4, "color": "orange"},
    {"label": "ST05", "value": 23.8, "color": "amber"},
    {"label": "ST26", "value": 23.7, "color": "amber"},
]

B28_MEETING_ROOMS = [
    {"label": "1.W.560", "value": 8, "color": "teal"},
    {"label": "2.E.340", "value": 6, "color": "teal"},
    {"label": "4.E.040", "value": 4, "color": "amber"},
    {"label": "4.E.100", "value": 2, "color": "red"},
    {"label": "5.W.920", "value": 0, "color": "grey"},
]


# ── HHS: open-plan-office operations dashboard ───────────────────────
HHS_DASHBOARD = {
    "type": "column",
    "crossAxisAlignment": "stretch",
    "children": [
        {
            "type": "image_banner",
            "title": "HHS office floor — 28 strips",
            "subtitle": "Open-plan operations · floor 0",
            "color": "indigo",
        },
        {"type": "spacer", "height": 12},
        {
            "type": "row",
            "children": [
                {
                    "type": "weather_badge",
                    "temp": "13",
                    "unit": "°C",
                    "label": "The Hague",
                    "icon": "cloud",
                },
                {
                    "type": "badge_row",
                    "badges": [
                        {"label": "BMS connected", "color": "green"},
                        {"label": "28 strips", "color": "teal"},
                        {"label": "Floor 0", "color": "indigo"},
                    ],
                },
            ],
        },
        {"type": "spacer", "height": 16},
        {"type": "section_header", "title": "Floor pulse", "icon": "monitor_heart"},
        {"type": "spacer", "height": 8},
        {
            "type": "grid",
            "columns": 2,
            "spacing": 10,
            "children": [
                {"type": "kpi_card", "label": "Avg temperature", "value": "22.7", "unit": "°C", "trend": "up"},
                {"type": "kpi_card", "label": "Avg CO₂",         "value": "612",  "unit": "ppm", "trend": "down"},
                {"type": "kpi_card", "label": "Strips occupied", "value": "19",   "unit": "/ 28", "trend": "up"},
                {"type": "kpi_card", "label": "Comfort score",   "value": "78",   "unit": "%",   "trend": "up"},
            ],
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Temperature heatmap", "icon": "thermostat"},
        {"type": "spacer", "height": 8},
        {
            "type": "heatmap_strip",
            "title": "All 28 strips · current temperature",
            "unit": "°",
            "min": 19,
            "max": 26,
            "columns": 7,
            "cells": HHS_HEATMAP_CELLS,
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Temperature trend", "icon": "thermometer"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "temperature",
            "title": "Temperature (area)",
            "unit": "°C",
            "groupBy": "room",
            "height": 260,
            "chartKind": "area",
            "timeRanges": [
                {"label": "Last 6 hours",  "hours": 6,   "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24,  "granularity": "hourly"},
                {"label": "Last 7 days",   "hours": 168, "granularity": "hourly"},
            ],
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "CO₂ — latest by strip", "icon": "co2"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "co2",
            "title": "CO₂ (ranked)",
            "unit": "ppm",
            "groupBy": "room",
            "height": 320,
            "chartKind": "bar",
            "timeRanges": [
                {"label": "Last hour",     "hours": 1,  "granularity": "raw"},
                {"label": "Last 24 hours", "hours": 24, "granularity": "hourly"},
            ],
        },
        {"type": "spacer", "height": 20},
        {
            "type": "bar_list",
            "title": "Hottest strips right now",
            "unit": "°C",
            "items": HHS_HOTTEST,
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Operations", "icon": "info"},
        {"type": "spacer", "height": 4},
        {"type": "stat_row", "icon": "wifi",     "label": "Sensors reporting", "value": "84 / 84"},
        {"type": "stat_row", "icon": "schedule", "label": "Last BMS poll",     "value": "2 min ago"},
        {"type": "stat_row", "icon": "warning",  "label": "Open complaints",   "value": "3"},
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


# ── Building 28: meeting-room / occupant comfort dashboard ──────────
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
            "temp": "14",
            "unit": "°C",
            "label": "The Hague — sunny",
            "icon": "wb_sunny",
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
                    "value": 21.4,
                    "min": 16,
                    "max": 28,
                    "unit": "°C",
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
                    "value": 742,
                    "min": 400,
                    "max": 1500,
                    "unit": "ppm",
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
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Meeting rooms today", "icon": "people"},
        {"type": "spacer", "height": 8},
        {
            "type": "bar_list",
            "title": "Free hours remaining",
            "unit": "h",
            "items": B28_MEETING_ROOMS,
        },
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Your schedule", "icon": "schedule"},
        {"type": "spacer", "height": 4},
        {
            "type": "schedule_item",
            "time": "09:00",
            "title": "Standup — Project Kestrel",
            "subtitle": "Until 09:30 · 4.E.040",
        },
        {
            "type": "schedule_item",
            "time": "11:00",
            "title": "1:1 with M. de Vries",
            "subtitle": "Until 11:45 · 2.E.340",
        },
        {
            "type": "schedule_item",
            "time": "14:00",
            "title": "Design review",
            "subtitle": "Until 15:30 · 1.W.560",
        },
        {"type": "spacer", "height": 16},
        {
            "type": "badge_row",
            "badges": [
                {"label": "Heating ON",  "color": "teal"},
                {"label": "Vent ECO",    "color": "green"},
                {"label": "Quiet hours", "color": "blue"},
            ],
        },
        {"type": "spacer", "height": 20},
        {
            "type": "alert_banner",
            "icon": "info",
            "title": "Tell us how it feels",
            "subtitle": "A 10-second vote helps your building learn what works.",
            "color": "teal",
        },
        {"type": "spacer", "height": 8},
        {"type": "primary_action", "label": "Submit comfort vote"},
    ],
}


def _existing_api_key(conn, building_id: str) -> str | None:
    """Return telemetryApiKey from the latest active config, if any."""
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
    """Upsert dashboard_layout on the latest active config, or create one."""
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
    """Restore minimal layouts (only telemetryApiKey, if any)."""
    conn = op.get_bind()
    for bid in (HHS_BUILDING_ID, B28_BUILDING_ID):
        existing_key = _existing_api_key(conn, bid)
        layout = {"telemetryApiKey": existing_key} if existing_key else {}
        _write_layout(conn, bid, layout)
