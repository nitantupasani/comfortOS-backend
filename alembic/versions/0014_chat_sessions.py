"""Add chat_sessions and chat_messages tables.

Revision ID: 0014_chat_sessions
Revises: 0013_complaints
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_chat_sessions"
down_revision = "0013_complaints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(50),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "building_id",
            sa.String(50),
            sa.ForeignKey("buildings.id"),
            nullable=True,
        ),
        sa.Column(
            "title",
            sa.String(200),
            nullable=False,
            server_default="New chat",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "message_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_building_id", "chat_sessions", ["building_id"])
    op.create_index(
        "ix_chat_sessions_last_message_at",
        "chat_sessions",
        ["last_message_at"],
    )
    op.create_index(
        "ix_chat_sessions_user_last",
        "chat_sessions",
        ["user_id", "last_message_at"],
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(50),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # role stored as a plain VARCHAR because the ORM defines the enum
        # with native_enum=False (matching the pattern used by other
        # string-enum columns in this project).
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chat_messages_session_id",
        "chat_messages",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_sessions_user_last", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_last_message_at", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_building_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
