"""Building Connector — registered external building service for pull-based telemetry.

ComfortOS polls each connector at a configured interval to fetch sensor readings.
Supports multiple authentication methods for secure machine-to-machine communication.

Auth types
----------
- ``bearer_token``             — Static token in Authorization header
- ``oauth2_client_credentials`` — OAuth 2.0 Client Credentials grant (M2M)
- ``mtls``                     — Mutual TLS with client certificates
- ``api_key``                  — Custom header with an API key
- ``basic_auth``               — HTTP Basic username/password
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class BuildingConnector(Base):
    """A registered building data service that ComfortOS polls for sensor data."""

    __tablename__ = "building_connectors"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        default=lambda: f"bconn-{uuid.uuid4().hex[:8]}",
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="Human-readable name (e.g. 'Siemens BMS Floor Sensors')",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    # ── Connection ──

    base_url: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="Full URL to poll (e.g. https://bms.example.com/api/v1/readings)",
    )
    http_method: Mapped[str] = mapped_column(
        String(10), nullable=False, default="GET",
        comment="HTTP method to use: GET or POST",
    )
    request_headers: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Extra static headers to include in poll requests",
    )
    request_body: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Static request body for POST requests",
    )

    # ── Authentication ──

    auth_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="bearer_token",
        comment="bearer_token | oauth2_client_credentials | mtls | api_key | basic_auth",
    )
    auth_config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict,
        comment="Auth credentials (see docs for per-type schema)",
    )

    # ── Response Mapping ──

    response_mapping: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Optional mapping from custom response format to ComfortOS schema",
    )

    # ── Available Metrics ──

    available_metrics: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="Metric types this connector provides, e.g. ['temperature','co2','humidity','noise']",
    )

    # ── Polling ──

    polling_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    # ── Status Tracking ──

    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="success | error | timeout",
    )
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    total_polls: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    total_readings_ingested: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # ── Timestamps ──

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    building = relationship("Building", backref="connectors")

    __table_args__ = (
        Index("ix_connector_building_enabled", "building_id", "is_enabled"),
    )

    def to_api_dict(self, *, mask_secrets: bool = True) -> dict:
        """Serialise for API response, optionally masking auth credentials."""
        d = {
            "id": self.id,
            "buildingId": self.building_id,
            "name": self.name,
            "description": self.description,
            "baseUrl": self.base_url,
            "httpMethod": self.http_method,
            "requestHeaders": self.request_headers,
            "requestBody": self.request_body,
            "authType": self.auth_type,
            "authConfig": self._masked_auth() if mask_secrets else self.auth_config,
            "responseMapping": self.response_mapping,
            "availableMetrics": self.available_metrics,
            "pollingIntervalMinutes": self.polling_interval_minutes,
            "isEnabled": self.is_enabled,
            "lastPolledAt": self.last_polled_at.isoformat() if self.last_polled_at else None,
            "lastStatus": self.last_status,
            "lastError": self.last_error,
            "consecutiveFailures": self.consecutive_failures,
            "totalPolls": self.total_polls,
            "totalReadingsIngested": self.total_readings_ingested,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }
        return d

    def _masked_auth(self) -> dict:
        """Return auth_config with secrets replaced by '••••••'."""
        if not self.auth_config:
            return {}
        masked = dict(self.auth_config)
        sensitive_keys = {
            "token", "clientSecret", "password", "apiKey",
            "secret", "clientKeyPem",
        }
        for k in sensitive_keys:
            if k in masked and masked[k]:
                masked[k] = "••••••"
        return masked
