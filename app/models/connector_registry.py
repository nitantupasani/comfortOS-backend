"""Connector and Dataset registries — maps to the Registry DB in backend.puml."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ConnectorDefinition(Base):
    """A registered connector to an external building data service.

    The Connector Gateway resolves these definitions when the Platform API
    requests a dataset read.
    """
    __tablename__ = "connector_definitions"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"conn-{uuid.uuid4().hex[:8]}"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    auth_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="oauth2"
    )  # mtls, oauth2, hmac
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret_ref: Mapped[str | None] = mapped_column(String(200))  # reference in Secrets Manager
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DatasetDefinition(Base):
    """A registered dataset mapping a logical key to a connector + endpoint.

    The Connector Gateway uses this to resolve where and how to fetch
    external building measurements.
    """
    __tablename__ = "dataset_definitions"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"ds-{uuid.uuid4().hex[:8]}"
    )
    dataset_key: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    connector_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("connector_definitions.id"), nullable=False
    )
    endpoint_path: Mapped[str] = mapped_column(String(500), nullable=False)
    response_mapping: Mapped[dict | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
