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
)

# API routers
from .api.auth import router as auth_router
from .api.buildings import router as buildings_router
from .api.tenants import router as tenants_router
from .api.votes import router as votes_router
from .api.presence import router as presence_router
from .api.datasets import router as datasets_router
from .api.fm_requests import router as fm_requests_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables (dev convenience). Shutdown: dispose engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
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


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "comfortos-platform-api"}
