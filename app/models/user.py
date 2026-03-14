"""User model with RBAC, tenant isolation, and location binding.

Roles
-----
- **occupant** — Regular building user who can vote / view dashboards.
- **tenant_facility_manager** — Manages comfort settings for *their tenant's*
  space only (cannot see other tenants' data).
- **building_facility_manager** — Manages the *entire building* across all
  tenants.
- **admin** — Platform-wide super-admin.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from ..database import Base


class UserRole(str, enum.Enum):
    occupant = "occupant"
    tenant_facility_manager = "tenant_facility_manager"
    building_facility_manager = "building_facility_manager"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"usr-{uuid.uuid4().hex[:8]}"
    )
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=True, default="FIREBASE_MANAGED")
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", create_constraint=False, native_enum=False),
        default=UserRole.occupant,
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("tenants.id"), nullable=True, index=True,
        comment="NULL for independent users (Google / email sign-up without org)",
    )
    claims: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    building_accesses = relationship(
        "UserBuildingAccess",
        back_populates="user",
        foreign_keys="[UserBuildingAccess.user_id]",
        lazy="selectin",
    )
