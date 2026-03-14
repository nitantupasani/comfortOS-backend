"""
Database seeder — populates demo data for multi-tenant smart building platform.

Run: python -m app.seed
"""

import asyncio
import json

from .database import engine, async_session_factory, Base
from .models.tenant import Tenant
from .models.user import User, UserRole
from .models.building import Building
from .models.building_tenant import BuildingTenant
from .models.user_building_access import UserBuildingAccess
from .models.building_config import BuildingConfig
from .models.presence import Beacon


# ── Demo SDUI Configs (subset from DummyBackend) ────────────────────────

BLDG_001_DASHBOARD = {
    "type": "column",
    "crossAxisAlignment": "stretch",
    "children": [
        {
            "type": "weather_badge",
            "temp": "15",
            "unit": "°C",
            "label": "Outside",
            "icon": "wb_sunny",
        },
        {"type": "spacer", "height": 8},
        {"type": "room_selector", "room": "Conference Room A"},
        {"type": "spacer", "height": 16},
        {
            "type": "grid",
            "columns": 3,
            "spacing": 10,
            "children": [
                {"type": "metric_tile", "icon": "thermostat", "value": "22.5", "unit": "°C", "label": "Temp"},
                {"type": "metric_tile", "icon": "co2", "value": "820", "unit": "ppm", "label": "CO2"},
                {"type": "metric_tile", "icon": "volume_up", "value": "45", "unit": "dB", "label": "Noise"},
            ],
        },
        {"type": "spacer", "height": 16},
        {
            "type": "trend_card",
            "title": "Temperature Trend",
            "subtitle": "Last 24 hours",
            "change": "+1.2°",
            "data": [15.0, 15.0, 18.0, 22.0, 25.0, 22.5],
            "labels": ["12AM", "6AM", "12PM", "6PM"],
        },
        {"type": "spacer", "height": 16},
        {
            "type": "alert_banner",
            "icon": "thermostat",
            "title": "Building is Warming Up",
            "subtitle": "HVAC system is adjusting to reach target temperature.",
            "color": "orange",
        },
    ],
}

VOTE_FORM_V2 = {
    "version": 2,
    "title": "How do you feel right now?",
    "fields": [
        {
            "id": "thermal_comfort",
            "type": "thermal_scale",
            "question": "How hot or cold do you feel?",
            "min": 1,
            "max": 7,
            "defaultValue": 4,
            "labels": {"1": "Cold", "4": "Neutral", "7": "Hot"},
            "required": True,
        },
        {
            "id": "air_quality",
            "type": "emoji_scale",
            "question": "How is the air quality?",
            "options": [
                {"value": 1, "emoji": "🤢", "label": "Stuffy"},
                {"value": 2, "emoji": "😐", "label": "Okay"},
                {"value": 3, "emoji": "😊", "label": "Fresh"},
            ],
            "required": True,
        },
        {
            "id": "noise_level",
            "type": "rating_stars",
            "question": "Rate the noise level",
            "maxStars": 5,
            "required": False,
        },
        {
            "id": "feedback",
            "type": "text_input",
            "question": "Any additional comments?",
            "required": False,
        },
    ],
}

LOCATION_FORM = {
    "floors": [
        {
            "id": "F1",
            "label": "Floor 1",
            "rooms": [
                {"id": "F1-R1", "label": "Lobby"},
                {"id": "F1-R2", "label": "Cafeteria"},
                {"id": "F1-R3", "label": "Conference Room A"},
            ],
        },
        {
            "id": "F2",
            "label": "Floor 2",
            "rooms": [
                {"id": "F2-R1", "label": "Open Office"},
                {"id": "F2-R2", "label": "Meeting Room B"},
                {"id": "F2-R3", "label": "Quiet Zone"},
            ],
        },
        {
            "id": "F3",
            "label": "Floor 3",
            "rooms": [
                {"id": "F3-R1", "label": "Executive Suite"},
                {"id": "F3-R2", "label": "Server Room"},
            ],
        },
    ],
}


async def seed():
    """Insert demo data into the database."""

    import os
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

    async with async_session_factory() as session:
        # ── Building ────────────────────────────────────────────────────
        vertigo_building = Building(
            id="bldg-vertigo",
            name="Vertigo",
            address="1 Vertigo Tower",
            city="Eindhoven",
            latitude=51.4416,
            longitude=5.4697,
            requires_access_permission=True,
            daily_vote_limit=10,
            metadata_={"floors": 1, "zones": 1},
        )
        session.add(vertigo_building)

        # ── Users ────────────────────────────────────────────────────────
        admin_user = User(
            id="usr-admin",
            email="admin@comfortos.com",
            name="Nitant Upasani",
            hashed_password="FIREBASE_MANAGED",
            role=UserRole.admin,
            tenant_id=None,
            claims={"scopes": ["admin", "manage_building", "vote", "view_dashboard"]},
        )
        occupant_user = User(
            id="usr-occupant",
            email="occupant@comfortos.com",
            name="Occupant",
            hashed_password="FIREBASE_MANAGED",
            role=UserRole.occupant,
            tenant_id=None,
            claims={"scopes": ["vote", "view_dashboard"]},
        )
        fm_user = User(
            id="usr-fm",
            email="fm@comfortos.com",
            name="Facility Manager",
            hashed_password="FIREBASE_MANAGED",
            role=UserRole.building_facility_manager,
            tenant_id=None,
            claims={"scopes": ["manage_building", "vote", "view_dashboard"]},
        )
        session.add_all([admin_user, occupant_user, fm_user])

        # ── User Building Access Grants ───────────────────────────────────
        access_grants = [
            UserBuildingAccess(
                id="uba-admin",
                user_id="usr-admin",
                building_id="bldg-vertigo",
                granted_by="usr-admin",
            ),
            UserBuildingAccess(
                id="uba-occupant",
                user_id="usr-occupant",
                building_id="bldg-vertigo",
                granted_by="usr-admin",
            ),
            UserBuildingAccess(
                id="uba-fm",
                user_id="usr-fm",
                building_id="bldg-vertigo",
                granted_by="usr-admin",
            ),
        ]
        session.add_all(access_grants)

        await session.commit()
        print("✓ Seeded: Vertigo building, admin, occupant, FM users, and access grants.")


if __name__ == "__main__":
    asyncio.run(seed())
