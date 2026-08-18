"""account-wide legal consent history

Revision ID: 20260817_0005
Revises: 20260730_0004
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260817_0005"
down_revision = "20260730_0004"
branch_labels = None
depends_on = None


def _uuid_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def upgrade():
    if inspect(op.get_bind()).has_table("legal_consents"):
        return

    op.create_table(
        "legal_consents",
        sa.Column("id", _uuid_type(), primary_key=True, nullable=False),
        sa.Column("user_id", _uuid_type(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("terms_version", sa.String(length=32), nullable=False),
        sa.Column("privacy_version", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "terms_version",
            "privacy_version",
            name="uq_legal_consent_versions",
        ),
    )
    op.create_index("ix_legal_consents_user_id", "legal_consents", ["user_id"], unique=False)


def downgrade():
    if inspect(op.get_bind()).has_table("legal_consents"):
        op.drop_index("ix_legal_consents_user_id", table_name="legal_consents")
        op.drop_table("legal_consents")
