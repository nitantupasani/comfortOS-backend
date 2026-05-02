"""Distinct minimal vote form for Building 28 (separate from HHS).

Three fields only:
  1. thermal_sensation : ASHRAE 55 7-point scale (Fanger PMV)
  2. clothing          : multi_select of garments. `value` is the
                          CLO contribution (ISO 9920 / ASHRAE 55).
                          Plain-language labels only — CLO numbers are
                          NOT shown to occupants (per memory note).
  3. overall_satisfaction : 5-point semantic differential
                            (very dissatisfied → very satisfied).

Also refreshes the B28 dashboard `vote_aggregate` node so its metrics
align with the new minimal schema.

HHS keeps the full research-backed form set in 0022.

Revision ID: 0023_b28_minimal_vote_form
Revises: 0022_research_vote_forms
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "0023_b28_minimal_vote_form"
down_revision = "0022_research_vote_forms"
branch_labels = None
depends_on = None


B28_BUILDING_ID = "bldg-28"


B28_VOTE_FORM = {
    "schemaVersion": 4,
    "version": 4,
    "formTitle": "Comfort check-in",
    "title": "Comfort check-in",
    "formDescription": "Three quick questions. Helps the building tune to how you feel right now.",
    "description": "Three quick questions. Helps the building tune to how you feel right now.",
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
            "id": "clothing",
            "key": "clothing",
            "type": "multi_select",
            "question": "What are you wearing right now?",
            "required": True,
            # Values are CLO contributions (ISO 9920 / ASHRAE 55).
            # Labels stay in plain language — CLO numbers are never
            # shown to occupants. Sum at analysis time for total CLO.
            "options": [
                {"value": 0.08, "label": "T-shirt",          "emoji": "👕"},
                {"value": 0.20, "label": "Long-sleeve shirt","emoji": "👔"},
                {"value": 0.25, "label": "Light sweater",    "emoji": "🧶"},
                {"value": 0.36, "label": "Heavy sweater",    "emoji": "🧥"},
                {"value": 0.36, "label": "Jacket or blazer", "emoji": "🧥"},
                {"value": 0.06, "label": "Shorts",           "emoji": "🩳"},
                {"value": 0.24, "label": "Trousers",         "emoji": "👖"},
                {"value": 0.14, "label": "Skirt (knee)",     "emoji": "👗"},
                {"value": 0.04, "label": "Closed shoes",     "emoji": "👟"},
                {"value": 0.02, "label": "Open shoes",       "emoji": "🩴"},
            ],
        },
        {
            "id": "overall_satisfaction",
            "key": "overall_satisfaction",
            "type": "single_select",
            "question": "Overall, how satisfied are you with the room right now?",
            "required": True,
            "options": [
                {"value": 1, "label": "Very dissatisfied", "color": "red",    "emoji": "😣"},
                {"value": 2, "label": "Dissatisfied",      "color": "orange", "emoji": "🙁"},
                {"value": 3, "label": "Neutral",           "color": "amber",  "emoji": "😐"},
                {"value": 4, "label": "Satisfied",         "color": "teal",   "emoji": "🙂"},
                {"value": 5, "label": "Very satisfied",    "color": "green",  "emoji": "😄"},
            ],
        },
    ],
}


# B28 dashboard with vote_aggregate metrics matching the new schema.
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
                {"id": "thermal_sensation",     "label": "Thermal comfort",       "color": "teal",   "kind": "thermal"},
                {"id": "overall_satisfaction", "label": "Overall satisfaction",  "color": "indigo", "kind": "overall"},
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
    _write_vote_form(conn, B28_BUILDING_ID, B28_VOTE_FORM)

    merged = dict(B28_DASHBOARD)
    existing_key = _existing_api_key(conn, B28_BUILDING_ID)
    if existing_key:
        merged["telemetryApiKey"] = existing_key
    _write_dashboard(conn, B28_BUILDING_ID, merged)


def downgrade() -> None:
    """No-op: previous form / dashboard from 0022 stay in place."""
    pass
