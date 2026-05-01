"""Configure research-backed vote forms for HHS and Building 28.

Replaces existing vote_form_schema for both buildings with a schema
grounded in established indoor environment research:

  * thermal_sensation : ASHRAE 55 7-point scale (Fanger PMV)
  * thermal_preference: McIntyre 3-point preference (cooler / no change / warmer)
  * thermal_acceptable: ASHRAE 55 acceptability (binary)
  * air_quality       : 5-point semantic differential (very stuffy → very fresh)
  * acoustic_comfort  : 5-point centered preference, no stars
  * adaptive_actions  : de Dear / Brager adaptive comfort framework
  * comments          : free text

No `rating_stars` fields anywhere.

Also updates the Building 28 dashboard layout's `vote_aggregate` node
so its metric ids match the new vote schema keys (thermal_sensation,
air_quality with `air_5pt` kind, acoustic_comfort).

Revision ID: 0022_research_vote_forms
Revises: 0021_remove_em_dashes
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "0022_research_vote_forms"
down_revision = "0021_remove_em_dashes"
branch_labels = None
depends_on = None


HHS_BUILDING_ID = "bldg-5e32215a"
B28_BUILDING_ID = "bldg-28"


# ── Research-backed vote form (shared by both buildings) ────────────
RESEARCH_VOTE_FORM = {
    "schemaVersion": 3,
    "version": 3,
    "formTitle": "Comfort check-in",
    "title": "Comfort check-in",
    "formDescription": "About 30 seconds. Helps the building tune to how you feel right now.",
    "description": "About 30 seconds. Helps the building tune to how you feel right now.",
    "thanksMessage": "Thanks for your feedback!",
    "allowAnonymous": False,
    "cooldownMinutes": 30,
    "fields": [
        {
            "id": "thermal_sensation",
            "key": "thermal_sensation",
            "type": "thermal_scale",
            "question": "How do you feel right now?",
            "required": True,
            "min": -3,
            "max": 3,
            "defaultValue": 0,
            "labels": {
                "-3": "Cold",
                "-2": "Cool",
                "-1": "Slightly cool",
                "0":  "Neutral",
                "1":  "Slightly warm",
                "2":  "Warm",
                "3":  "Hot",
            },
            "hint": "ASHRAE 7-point thermal sensation",
        },
        {
            "id": "thermal_preference",
            "key": "thermal_preference",
            "type": "single_select",
            "question": "Right now, you would prefer to be:",
            "required": True,
            "options": [
                {"value": -1, "label": "Cooler",    "color": "blue",   "emoji": "❄️"},
                {"value": 0,  "label": "No change", "color": "green",  "emoji": "👍"},
                {"value": 1,  "label": "Warmer",    "color": "orange", "emoji": "🔥"},
            ],
        },
        {
            "id": "thermal_acceptable",
            "key": "thermal_acceptable",
            "type": "yes_no",
            "question": "Is the temperature acceptable to you?",
            "required": True,
            "yesLabel": "Acceptable",
            "noLabel":  "Not acceptable",
        },
        {
            "id": "air_quality",
            "key": "air_quality",
            "type": "single_select",
            "question": "How is the air in here?",
            "required": True,
            "options": [
                {"value": 1, "label": "Very stuffy", "color": "red"},
                {"value": 2, "label": "Stuffy",      "color": "orange"},
                {"value": 3, "label": "Neutral",     "color": "amber"},
                {"value": 4, "label": "Fresh",       "color": "teal"},
                {"value": 5, "label": "Very fresh",  "color": "green"},
            ],
        },
        {
            "id": "acoustic_comfort",
            "key": "acoustic_comfort",
            "type": "single_select",
            "question": "How is the sound level?",
            "required": False,
            "options": [
                {"value": -2, "label": "Much too quiet",  "color": "blue"},
                {"value": -1, "label": "A bit too quiet", "color": "cyan"},
                {"value": 0,  "label": "Just right",      "color": "green"},
                {"value": 1,  "label": "A bit too noisy", "color": "amber"},
                {"value": 2,  "label": "Much too noisy",  "color": "red"},
            ],
        },
        {
            "id": "adaptive_actions",
            "key": "adaptive_actions",
            "type": "multi_select",
            "question": "Anything you have already tried?",
            "required": False,
            "options": [
                {"value": "added_layer",   "label": "Added a layer",     "emoji": "🧥"},
                {"value": "removed_layer", "label": "Removed a layer",   "emoji": "👕"},
                {"value": "opened_window", "label": "Opened a window",   "emoji": "🪟"},
                {"value": "fan",           "label": "Used a fan",        "emoji": "🌀"},
                {"value": "moved",         "label": "Moved seats",       "emoji": "🚶"},
                {"value": "drink",         "label": "Hot or cold drink", "emoji": "☕"},
                {"value": "none",          "label": "Nothing", "exclusive": True, "color": "grey"},
            ],
        },
        {
            "id": "comments",
            "key": "comments",
            "type": "text_input",
            "question": "Anything else? (optional)",
            "required": False,
            "maxLength": 280,
        },
    ],
}


# ── B28 dashboard, with vote_aggregate metrics updated ──────────────
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
            "label": "The Hague", "icon": "wb_sunny",
        },
        {"type": "spacer", "height": 12},
        {"type": "room_selector", "room": "Meeting Room 4.E.040, East Wing"},
        {"type": "spacer", "height": 16},
        {"type": "section_header", "title": "This room right now", "icon": "thermostat"},
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
        {"type": "spacer", "height": 24},
        {"type": "section_header", "title": "Compare floors: temperature", "icon": "apartment"},
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
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Compare floors: CO₂", "icon": "co2"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "co2",
            "title": "CO₂ by floor",
            "unit": "ppm",
            "height": 260,
            "chartKind": "area",
            "mode": "floor",
            "lockMode": True,
            "timeRanges": [
                {"label": "Last hour",     "hours": 1,   "granularity": "raw"},
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
                {"id": "thermal_sensation", "label": "Thermal comfort",   "color": "teal",  "kind": "thermal"},
                {"id": "air_quality",       "label": "Air freshness",     "color": "amber", "kind": "air_5pt"},
                {"id": "acoustic_comfort",  "label": "Acoustic comfort",  "color": "teal",  "kind": "acoustic"},
                {"id": "thermal_acceptable","label": "Temp. acceptability","color": "indigo","kind": "acceptability"},
            ],
        },
        {"type": "spacer", "height": 24},
        {"type": "section_header", "title": "Compare wings: temperature", "icon": "business"},
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
        {"type": "spacer", "height": 20},
        {"type": "section_header", "title": "Compare wings: CO₂", "icon": "co2"},
        {"type": "spacer", "height": 8},
        {
            "type": "telemetry_chart",
            "metricType": "co2",
            "title": "CO₂: East vs West",
            "unit": "ppm",
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


def _write_dashboard(conn, building_id: str, layout: dict) -> None:
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


def _write_vote_form(conn, building_id: str, schema: dict) -> None:
    payload = json.dumps(schema)
    result = conn.execute(
        sa.text(
            "UPDATE building_configs SET "
            "  vote_form_schema = CAST(:schema AS jsonb), "
            "  updated_at = NOW() "
            "WHERE id = ("
            "  SELECT id FROM building_configs "
            "  WHERE building_id = :bid AND is_active = true "
            "  ORDER BY created_at DESC LIMIT 1"
            ")"
        ).bindparams(schema=payload, bid=building_id)
    )
    if result.rowcount == 0:
        conn.execute(
            sa.text(
                "INSERT INTO building_configs "
                "  (id, building_id, schema_version, vote_form_schema, is_active, created_at, updated_at) "
                "VALUES "
                "  (:id, :bid, 1, CAST(:schema AS jsonb), true, NOW(), NOW())"
            ).bindparams(
                id=f"cfgv-{building_id[-8:]}",
                bid=building_id,
                schema=payload,
            )
        )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Set research-backed vote form for both buildings.
    for bid in (HHS_BUILDING_ID, B28_BUILDING_ID):
        _write_vote_form(conn, bid, RESEARCH_VOTE_FORM)

    # 2. Refresh B28 dashboard layout so vote_aggregate metrics align
    #    with the new vote field keys (and `air_5pt` / `acoustic` /
    #    `acceptability` aggregator kinds).
    merged = dict(B28_DASHBOARD)
    existing_key = _existing_api_key(conn, B28_BUILDING_ID)
    if existing_key:
        merged["telemetryApiKey"] = existing_key
    _write_dashboard(conn, B28_BUILDING_ID, merged)


def downgrade() -> None:
    """No-op: previous vote forms / B28 layout stay in place."""
    pass
