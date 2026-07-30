"""caregiver friend request system

Revision ID: 20260730_0004
Revises: 20260719_0003
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260730_0004"
down_revision = "20260719_0003"
branch_labels = None
depends_on = None


def _uuid_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def _has_column(table_name, column_name):
    bind = op.get_bind()
    return column_name in {col["name"] for col in inspect(bind).get_columns(table_name)}


def _has_table(table_name):
    return inspect(op.get_bind()).has_table(table_name)


def upgrade():
    uuid = _uuid_type()

    if not _has_column("users", "caregiver_search_enabled"):
        op.add_column(
            "users",
            sa.Column("caregiver_search_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    if not _has_table("caregiver_messages"):
        op.create_table(
            "caregiver_messages",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("link_id", uuid, sa.ForeignKey("caregiver_links.id"), nullable=False),
            sa.Column("sender_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("recipient_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("message_key", sa.String(length=50), nullable=False),
            sa.Column("message_text", sa.String(length=255), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_caregiver_messages_link_id", "caregiver_messages", ["link_id"], unique=False)
        op.create_index("ix_caregiver_messages_sender_id", "caregiver_messages", ["sender_id"], unique=False)
        op.create_index("ix_caregiver_messages_recipient_id", "caregiver_messages", ["recipient_id"], unique=False)


def downgrade():
    if _has_table("caregiver_messages"):
        op.drop_index("ix_caregiver_messages_recipient_id", table_name="caregiver_messages")
        op.drop_index("ix_caregiver_messages_sender_id", table_name="caregiver_messages")
        op.drop_index("ix_caregiver_messages_link_id", table_name="caregiver_messages")
        op.drop_table("caregiver_messages")
    if _has_column("users", "caregiver_search_enabled"):
        op.drop_column("users", "caregiver_search_enabled")
