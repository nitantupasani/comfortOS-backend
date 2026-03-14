"""FM Role Request model — tracks requests from occupants to become Facility Managers.

Users submit a request specifying a building. The admin reviews and approves/rejects.
On approval, the user's role is upgraded and building access is granted.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from ..database import Base


class FMRequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class FMRoleRequest(Base):
    __tablename__ = "fm_role_requests"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"fmreq-{uuid.uuid4().hex[:8]}"
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=False, index=True,
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True,
    )
    role_requested: Mapped[str] = mapped_column(
        String(50), nullable=False, default="building_facility_manager",
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[FMRequestStatus] = mapped_column(
        SAEnum(FMRequestStatus, name="fm_request_status", create_constraint=False, native_enum=False),
        default=FMRequestStatus.pending,
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    building = relationship("Building", foreign_keys=[building_id], lazy="selectin")
