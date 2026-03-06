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
from .services.auth_service import hash_password


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
            "question": "How do you feel thermally?",
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # ── Tenants ──────────────────────────────────────────────────────
        tenant_tesla = Tenant(
            id="tenant-tesla",
            name="Tesla Inc.",
            email_domain="tesla.com",
            auth_provider="google",
        )
        tenant_google = Tenant(
            id="tenant-google",
            name="Google LLC",
            email_domain="google.com",
            auth_provider="google",
        )
        session.add_all([tenant_tesla, tenant_google])

        # ── Buildings ────────────────────────────────────────────────────
        #  Open buildings — anyone with an account can view & vote
        #  Restricted buildings — only tenant-mapped users can access
        buildings = [
            # OPEN — public library study hall
            Building(
                id="bldg-001",
                name="City Central Library",
                address="100 Main Street",
                city="San Francisco",
                latitude=37.7749,
                longitude=-122.4194,
                requires_access_permission=False,
                daily_vote_limit=10,
                metadata_={"floors": 3, "zones": 9},
            ),
            # OPEN — co-working space
            Building(
                id="bldg-002",
                name="OpenDesk Co-Working",
                address="42 Innovation Ave",
                city="Austin",
                latitude=30.2672,
                longitude=-97.7431,
                requires_access_permission=False,
                daily_vote_limit=5,
                metadata_={"floors": 2, "zones": 6},
            ),
            # RESTRICTED — Tesla HQ, only Tesla employees
            Building(
                id="bldg-003",
                name="Tesla HQ",
                address="3500 Deer Creek Road",
                city="Palo Alto",
                latitude=37.3947,
                longitude=-122.1503,
                requires_access_permission=True,
                daily_vote_limit=20,
                metadata_={"floors": 5, "zones": 15},
            ),
            # RESTRICTED — Googleplex
            Building(
                id="bldg-004",
                name="Googleplex",
                address="1600 Amphitheatre Parkway",
                city="Mountain View",
                latitude=37.4220,
                longitude=-122.0841,
                requires_access_permission=True,
                daily_vote_limit=20,
                metadata_={"floors": 4, "zones": 20},
            ),
            # RESTRICTED — multi-tenant tower (both Tesla + Google)
            Building(
                id="bldg-005",
                name="Innovation Tower",
                address="1 Startup Blvd",
                city="San Jose",
                latitude=37.3382,
                longitude=-121.8863,
                requires_access_permission=True,
                daily_vote_limit=15,
                metadata_={"floors": 12, "zones": 36},
            ),
        ]
        session.add_all(buildings)

        # ── BuildingTenant mappings ──────────────────────────────────────
        building_tenants = [
            # Tesla → Tesla HQ (exclusive)
            BuildingTenant(
                id="bt-001",
                building_id="bldg-003",
                tenant_id="tenant-tesla",
                floors=[
                    {"id": "F1", "label": "Floor 1"},
                    {"id": "F2", "label": "Floor 2"},
                    {"id": "F3", "label": "Floor 3"},
                    {"id": "F4", "label": "Floor 4"},
                    {"id": "F5", "label": "Floor 5"},
                ],
            ),
            # Google → Googleplex (exclusive)
            BuildingTenant(
                id="bt-002",
                building_id="bldg-004",
                tenant_id="tenant-google",
                floors=[
                    {"id": "F1", "label": "Floor 1"},
                    {"id": "F2", "label": "Floor 2"},
                    {"id": "F3", "label": "Floor 3"},
                    {"id": "F4", "label": "Floor 4"},
                ],
            ),
            # Tesla → Innovation Tower (floors 3-6)
            BuildingTenant(
                id="bt-003",
                building_id="bldg-005",
                tenant_id="tenant-tesla",
                floors=[
                    {"id": "F3", "label": "Floor 3 – Tesla"},
                    {"id": "F4", "label": "Floor 4 – Tesla"},
                    {"id": "F5", "label": "Floor 5 – Tesla"},
                    {"id": "F6", "label": "Floor 6 – Tesla"},
                ],
                zones=[
                    {"id": "F3-Z1", "label": "Tesla Open Office"},
                    {"id": "F4-Z1", "label": "Tesla Engineering"},
                ],
            ),
            # Google → Innovation Tower (floors 7-10)
            BuildingTenant(
                id="bt-004",
                building_id="bldg-005",
                tenant_id="tenant-google",
                floors=[
                    {"id": "F7", "label": "Floor 7 – Google"},
                    {"id": "F8", "label": "Floor 8 – Google"},
                    {"id": "F9", "label": "Floor 9 – Google"},
                    {"id": "F10", "label": "Floor 10 – Google"},
                ],
                zones=[
                    {"id": "F7-Z1", "label": "Google Cloud Team"},
                    {"id": "F8-Z1", "label": "Google AI Lab"},
                ],
            ),
        ]
        session.add_all(building_tenants)

        # ── Users ────────────────────────────────────────────────────────
        users = [
            # Tesla occupant (domain-matched)
            User(
                id="usr-001",
                email="alice@tesla.com",
                name="Alice (Tesla Occupant)",
                hashed_password=hash_password("password"),
                role=UserRole.occupant,
                tenant_id="tenant-tesla",
                claims={"scopes": ["vote", "view_dashboard"]},
            ),
            # Tesla facility manager — can only see Tesla's space
            User(
                id="usr-002",
                email="bob@tesla.com",
                name="Bob (Tesla FM)",
                hashed_password=hash_password("password"),
                role=UserRole.tenant_facility_manager,
                tenant_id="tenant-tesla",
                claims={"scopes": ["vote", "view_dashboard", "manage_building"]},
            ),
            # Google occupant
            User(
                id="usr-003",
                email="carol@google.com",
                name="Carol (Google Occupant)",
                hashed_password=hash_password("password"),
                role=UserRole.occupant,
                tenant_id="tenant-google",
                claims={"scopes": ["vote", "view_dashboard"]},
            ),
            # Platform admin (no specific tenant)
            User(
                id="usr-004",
                email="admin@comfort.io",
                name="Dave (Platform Admin)",
                hashed_password=hash_password("password"),
                role=UserRole.admin,
                tenant_id=None,
                claims={"scopes": ["vote", "view_dashboard", "manage_building", "admin"]},
            ),
            # Independent user — signed up with Gmail, no tenant
            User(
                id="usr-005",
                email="eve@gmail.com",
                name="Eve (Independent User)",
                hashed_password=hash_password("password"),
                role=UserRole.occupant,
                tenant_id=None,
                claims={"scopes": ["vote", "view_dashboard"]},
            ),
            # Building facility manager — manages entire buildings
            User(
                id="usr-006",
                email="frank@comfort.io",
                name="Frank (Building FM)",
                hashed_password=hash_password("password"),
                role=UserRole.building_facility_manager,
                tenant_id=None,
                claims={"scopes": ["vote", "view_dashboard", "manage_building"]},
            ),
        ]
        session.add_all(users)

        # ── User Building Access Grants ───────────────────────────────────
        #  Explicit per-user access to specific buildings.
        #  Tenant-based access (via building_tenants) is automatic;
        #  these grants add *extra* building access on top.
        access_grants = [
            # Alice (Tesla) → Tesla HQ
            UserBuildingAccess(
                id="uba-001",
                user_id="usr-001",
                building_id="bldg-003",
                granted_by="usr-004",
            ),
            # Alice (Tesla) → Innovation Tower (cross-building access)
            UserBuildingAccess(
                id="uba-002",
                user_id="usr-001",
                building_id="bldg-005",
                granted_by="usr-002",
            ),
            # Bob (Tesla FM) → Tesla HQ
            UserBuildingAccess(
                id="uba-003",
                user_id="usr-002",
                building_id="bldg-003",
                granted_by="usr-004",
            ),
            # Bob (Tesla FM) → Innovation Tower
            UserBuildingAccess(
                id="uba-004",
                user_id="usr-002",
                building_id="bldg-005",
                granted_by="usr-004",
            ),
            # Carol (Google) → Googleplex
            UserBuildingAccess(
                id="uba-005",
                user_id="usr-003",
                building_id="bldg-004",
                granted_by="usr-004",
            ),
            # Carol (Google) → Innovation Tower (Google floors)
            UserBuildingAccess(
                id="uba-006",
                user_id="usr-003",
                building_id="bldg-005",
                granted_by="usr-004",
            ),
            # Eve (independent) → Innovation Tower (granted by admin)
            UserBuildingAccess(
                id="uba-007",
                user_id="usr-005",
                building_id="bldg-005",
                granted_by="usr-004",
            ),
        ]
        session.add_all(access_grants)

        # ── Building Configs ─────────────────────────────────────────────
        configs = [
            BuildingConfig(
                id="cfg-001",
                building_id="bldg-001",
                schema_version=2,
                dashboard_layout=BLDG_001_DASHBOARD,
                vote_form_schema=VOTE_FORM_V2,
                location_form_config=LOCATION_FORM,
                is_active=True,
            ),
            BuildingConfig(
                id="cfg-003",
                building_id="bldg-003",
                schema_version=2,
                dashboard_layout=None,
                vote_form_schema=VOTE_FORM_V2,
                location_form_config=LOCATION_FORM,
                is_active=True,
            ),
        ]
        session.add_all(configs)

        # ── BLE Beacons ──────────────────────────────────────────────────
        beacons = [
            Beacon(
                id="bcn-001",
                building_id="bldg-001",
                uuid_str="B001-A",
                label="Library Main Entrance",
            ),
            Beacon(
                id="bcn-002",
                building_id="bldg-003",
                uuid_str="B003-A",
                label="Tesla HQ Lobby",
            ),
        ]
        session.add_all(beacons)

        await session.commit()
        print(
            "✓ Seeded: 2 tenants (Tesla, Google), 5 buildings "
            "(2 open, 3 restricted), 4 building-tenant mappings, "
            "6 users (2 Tesla, 1 Google, 1 admin, 1 independent, 1 building FM), "
            "7 user-building-access grants, 2 configs, 2 beacons"
        )


if __name__ == "__main__":
    asyncio.run(seed())
