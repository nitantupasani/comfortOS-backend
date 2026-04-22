"""Complaint models — occupant-raised complaints scoped to a building.

Data model
----------
- **Complaint** — raised by one user against one building. Types: hot, cold,
  air_quality, cleanliness, other.
- **ComplaintCosign** — any user with access to the building can co-sign a
  complaint to boost its priority. Unique per (complaint, user).
- **ComplaintComment** — FMs (or admins) reply to a complaint. Occupants
  cannot comment.

The creator is auto-cosigned on creation so the initial priority reflects
their own support.
"""

import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Text, UniqueConstraint, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ComplaintType(str, enum.Enum):
    hot = "hot"
    cold = "cold"
    air_quality = "air_quality"
    cleanliness = "cleanliness"
    other = "other"


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"cmp-{uuid.uuid4().hex[:8]}"
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True,
    )
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=False, index=True,
    )
    complaint_type: Mapped[ComplaintType] = mapped_column(
        SAEnum(ComplaintType, name="complaint_type", create_constraint=False, native_enum=False),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True,
    )

    # Relationships
    building = relationship("Building", foreign_keys=[building_id], lazy="selectin")
    author = relationship("User", foreign_keys=[created_by], lazy="selectin")
    cosigners = relationship(
        "ComplaintCosign",
        back_populates="complaint",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    comments = relationship(
        "ComplaintComment",
        back_populates="complaint",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ComplaintComment.created_at",
    )


class ComplaintCosign(Base):
    __tablename__ = "complaint_cosigns"
    __table_args__ = (
        UniqueConstraint("complaint_id", "user_id", name="uq_complaint_cosigns_complaint_user"),
    )

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"cs-{uuid.uuid4().hex[:8]}"
    )
    complaint_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    complaint = relationship("Complaint", back_populates="cosigners")
    user = relationship("User", foreign_keys=[user_id], lazy="selectin")


class ComplaintComment(Base):
    __tablename__ = "complaint_comments"

    id: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: f"cmt-{uuid.uuid4().hex[:8]}"
    )
    complaint_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    author_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=False, index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    complaint = relationship("Complaint", back_populates="comments")
    author = relationship("User", foreign_keys=[author_id], lazy="selectin")
