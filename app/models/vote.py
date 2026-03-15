"""Vote model — comfort vote with idempotency by voteUuid."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum
from typing import Optional

from ..database import Base


class VoteStatus(str, enum.Enum):
    pending = "pending"
    queued = "queued"
    submitted = "submitted"
    confirmed = "confirmed"
    failed = "failed"


class Vote(Base):
    __tablename__ = "votes"

    vote_uuid: Mapped[str] = mapped_column(
        String(50), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    building_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[VoteStatus] = mapped_column(
        SAEnum(VoteStatus, name="vote_status"), default=VoteStatus.confirmed
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    building = relationship("Building", back_populates="votes")
    user = relationship("User")

    def to_api_dict(self) -> dict:
        """Serialise to the JSON shape expected by the Flutter frontend."""
        return {
            "voteUuid": self.vote_uuid,
            "buildingId": self.building_id,
            "userId": self.user_id,
            "payload": self.payload,
            "schemaVersion": self.schema_version,
            "createdAt": self.created_at.isoformat(),
            "status": self.status.value,
        }
