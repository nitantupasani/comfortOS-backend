"""Add complaints, complaint_cosigns, complaint_comments tables.

Revision ID: 0013_complaints
Revises: 0012_building28_wings
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_complaints"
down_revision = "0012_building28_wings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "complaints",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "building_id",
            sa.String(50),
            sa.ForeignKey("buildings.id"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(50),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("complaint_type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_complaints_building_id", "complaints", ["building_id"])
    op.create_index("ix_complaints_created_by", "complaints", ["created_by"])
    op.create_index("ix_complaints_created_at", "complaints", ["created_at"])

    op.create_table(
        "complaint_cosigns",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "complaint_id",
            sa.String(50),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(50),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "complaint_id", "user_id", name="uq_complaint_cosigns_complaint_user"
        ),
    )
    op.create_index(
        "ix_complaint_cosigns_complaint_id", "complaint_cosigns", ["complaint_id"]
    )
    op.create_index("ix_complaint_cosigns_user_id", "complaint_cosigns", ["user_id"])

    op.create_table(
        "complaint_comments",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column(
            "complaint_id",
            sa.String(50),
            sa.ForeignKey("complaints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.String(50),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_complaint_comments_complaint_id", "complaint_comments", ["complaint_id"]
    )
    op.create_index(
        "ix_complaint_comments_author_id", "complaint_comments", ["author_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_complaint_comments_author_id", table_name="complaint_comments")
    op.drop_index("ix_complaint_comments_complaint_id", table_name="complaint_comments")
    op.drop_table("complaint_comments")

    op.drop_index("ix_complaint_cosigns_user_id", table_name="complaint_cosigns")
    op.drop_index("ix_complaint_cosigns_complaint_id", table_name="complaint_cosigns")
    op.drop_table("complaint_cosigns")

    op.drop_index("ix_complaints_created_at", table_name="complaints")
    op.drop_index("ix_complaints_created_by", table_name="complaints")
    op.drop_index("ix_complaints_building_id", table_name="complaints")
    op.drop_table("complaints")
