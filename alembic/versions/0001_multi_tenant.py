"""Initial schema — creates all tables for a fresh database.

Revision ID: 0001_multi_tenant
Revises: (none — initial)
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0001_multi_tenant"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tenants ───────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email_domain", sa.String(200), unique=True, nullable=True),
        sa.Column("auth_provider", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tenants_email_domain", "tenants", ["email_domain"])

    # ── buildings ─────────────────────────────────────────────────────────
    op.create_table(
        "buildings",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("requires_access_permission", sa.Boolean, server_default="false", nullable=False),
        sa.Column("daily_vote_limit", sa.Integer, server_default="10", nullable=False),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    # ── users ─────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("email", sa.String(254), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("hashed_password", sa.String(200), nullable=True),
        sa.Column("role", sa.String(50), server_default="occupant", nullable=False),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("claims", sa.JSON, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    # ── building_tenants ──────────────────────────────────────────────────
    op.create_table(
        "building_tenants",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("floors", sa.JSON, nullable=True),
        sa.Column("zones", sa.JSON, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_building_tenants_building_id", "building_tenants", ["building_id"])
    op.create_index("ix_building_tenants_tenant_id", "building_tenants", ["tenant_id"])

    # ── user_building_access ──────────────────────────────────────────────
    op.create_table(
        "user_building_access",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("user_id", sa.String(50), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("granted_by", sa.String(50), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_user_building_access_user_id", "user_building_access", ["user_id"])
    op.create_index("ix_user_building_access_building_id", "user_building_access", ["building_id"])

    # ── building_configs ──────────────────────────────────────────────────
    op.create_table(
        "building_configs",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("schema_version", sa.Integer, server_default="1", nullable=False),
        sa.Column("dashboard_layout", sa.JSON, nullable=True),
        sa.Column("vote_form_schema", sa.JSON, nullable=True),
        sa.Column("location_form_config", sa.JSON, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_building_configs_building_id", "building_configs", ["building_id"])

    # ── votes ─────────────────────────────────────────────────────────────
    op.create_table(
        "votes",
        sa.Column("vote_uuid", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("user_id", sa.String(50), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("schema_version", sa.Integer, server_default="1", nullable=False),
        sa.Column("status", sa.String(20), server_default="confirmed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_votes_building_id", "votes", ["building_id"])
    op.create_index("ix_votes_user_id", "votes", ["user_id"])

    # ── presence_events ───────────────────────────────────────────────────
    op.create_table(
        "presence_events",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("user_id", sa.String(50), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, server_default="0.5", nullable=False),
        sa.Column("is_verified", sa.Boolean, server_default="false", nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_presence_events_building_id", "presence_events", ["building_id"])
    op.create_index("ix_presence_events_user_id", "presence_events", ["user_id"])

    # ── beacons ───────────────────────────────────────────────────────────
    op.create_table(
        "beacons",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("building_id", sa.String(50), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("uuid", sa.String(100), nullable=False),
        sa.Column("major", sa.Integer, nullable=True),
        sa.Column("minor", sa.Integer, nullable=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_beacons_building_id", "beacons", ["building_id"])

    # ── push_tokens ───────────────────────────────────────────────────────
    op.create_table(
        "push_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(50), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("push_token", sa.String(500), nullable=False),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_push_tokens_user_id", "push_tokens", ["user_id"])

    # ── audit_log ─────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("user_id", sa.String(50), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("details", sa.JSON, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])

    # ── connector_definitions ─────────────────────────────────────────────
    op.create_table(
        "connector_definitions",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("auth_type", sa.String(20), server_default="oauth2", nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("secret_ref", sa.String(200), nullable=True),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("is_approved", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    # ── dataset_definitions ───────────────────────────────────────────────
    op.create_table(
        "dataset_definitions",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("dataset_key", sa.String(100), unique=True, nullable=False),
        sa.Column("connector_id", sa.String(50), sa.ForeignKey("connector_definitions.id"), nullable=False),
        sa.Column("endpoint_path", sa.String(500), nullable=False),
        sa.Column("response_mapping", sa.JSON, nullable=True),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("is_approved", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_dataset_definitions_dataset_key", "dataset_definitions", ["dataset_key"], unique=True)


def downgrade() -> None:
    op.drop_table("dataset_definitions")
    op.drop_table("connector_definitions")
    op.drop_table("audit_log")
    op.drop_table("push_tokens")
    op.drop_table("beacons")
    op.drop_table("presence_events")
    op.drop_table("votes")
    op.drop_table("building_configs")
    op.drop_table("user_building_access")
    op.drop_table("building_tenants")
    op.drop_table("users")
    op.drop_table("buildings")
    op.drop_table("tenants")
