"""Chat session + message models.

Each authenticated user has zero-or-more chat sessions with Vos, the
ComfortOS AI persona. A session is tied to the building selected at
creation time (if any) and keeps the full message transcript so users
can reopen old conversations from their profile.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Integer,
    Enum as SAEnum,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ChatMessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        default=lambda: f"chs-{uuid.uuid4().hex[:12]}",
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=False, index=True,
    )
    building_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("buildings.id"), nullable=True, index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user = relationship("User", foreign_keys=[user_id], lazy="noload")
    building = relationship("Building", foreign_keys=[building_id], lazy="noload")
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChatMessage.created_at",
    )

    __table_args__ = (
        Index("ix_chat_sessions_user_last", "user_id", "last_message_at"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        default=lambda: f"msg-{uuid.uuid4().hex[:12]}",
    )
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[ChatMessageRole] = mapped_column(
        SAEnum(
            ChatMessageRole,
            name="chat_message_role",
            create_constraint=False,
            native_enum=False,
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    session = relationship("ChatSession", back_populates="messages")
