"""
ComfortOS Production Backend — FastAPI Application Entry Point.

Implements the C4 architecture from backend.puml:

  Container: Platform API (REST)
    - AuthZ, tenancy isolation, dashboard delivery, votes, tickets, dataset reads

  Container: Identity Provider (OIDC/OAuth2 — built-in routes)
    - Login, tokens, roles/claims

  Container: Connector Gateway (service module)
    - Secure egress, secret resolution, normalization, caching, SSRF defenses
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import engine, Base
from .middleware.rate_limiter import RateLimitMiddleware

# Import all models so SQLAlchemy registers them before create_all.
from .models import (  # noqa: F401
    Tenant,
    User,
    UserRole,
    Building,
    BuildingTenant,
    UserBuildingAccess,
    BuildingConfig,
    Vote,
    PresenceEvent,
    Beacon,
    PushToken,
    AuditLog,
    ConnectorDefinition,
    DatasetDefinition,
    FMRoleRequest,
    FMRequestStatus,
    TelemetryReading,
    BuildingConnector,
    Complaint,
    ComplaintCosign,
    ComplaintComment,
    ComplaintType,
    # Telemetry integration
    Location,
    Zone,
    ZoneMember,
    TelemetryEndpoint,
    Sensor,
    BuildingTelemetryConfig,
)

# API routers
from .api.auth import router as auth_router
from .api.buildings import router as buildings_router
from .api.tenants import router as tenants_router
from .api.votes import router as votes_router
from .api.presence import router as presence_router
from .api.datasets import router as datasets_router
from .api.fm_requests import router as fm_requests_router
from .api.complaints import router as complaints_router
from .api.telemetry import router as telemetry_router
from .api.connectors import router as connectors_router
from .api.ai import router as ai_router
# Telemetry integration routers
from .api.locations import router as locations_router
from .api.sensors import router as sensors_router
from .api.zones import router as zones_router
from .api.telemetry_endpoints import router as telemetry_endpoints_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables + start telemetry poller. Shutdown: cancel + dispose."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start background telemetry poller
    from .services.telemetry_poller import start_polling_loop
    poller_task = asyncio.create_task(start_polling_loop())

    yield

    poller_task.cancel()
    await engine.dispose()


app = FastAPI(
    title="ComfortOS Platform API",
    description=(
        "Production backend for the ComfortOS Smart Building Platform. "
        "Implements the architecture described in backend.puml."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

# ── Routers ──────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(buildings_router)
app.include_router(tenants_router)
app.include_router(votes_router)
app.include_router(presence_router)
app.include_router(datasets_router)
app.include_router(fm_requests_router)
app.include_router(complaints_router)
app.include_router(telemetry_router)
app.include_router(connectors_router)
app.include_router(ai_router)
# Telemetry integration
app.include_router(locations_router)
app.include_router(sensors_router)
app.include_router(zones_router)
app.include_router(telemetry_endpoints_router)


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "comfortos-platform-api"}
