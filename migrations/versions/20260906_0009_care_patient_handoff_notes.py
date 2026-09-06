"""care patient handoff notes

Revision ID: 20260906_0009
Revises: 20260906_0008
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260906_0009"
down_revision = "20260906_0008"
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def upgrade():
    if inspect(op.get_bind()).has_table("care_patient_handoff_notes"):
        return
    uuid = _uuid_type()
    op.create_table(
        "care_patient_handoff_notes",
        sa.Column("id", uuid, primary_key=True, nullable=False),
        sa.Column("patient_id", uuid, sa.ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tags", sa.String(length=255), server_default="", nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_care_patient_handoff_notes_patient_id", "care_patient_handoff_notes", ["patient_id"])
    op.create_index("ix_care_patient_handoff_notes_author_user_id", "care_patient_handoff_notes", ["author_user_id"])
    op.create_index("ix_care_patient_handoff_notes_created_at", "care_patient_handoff_notes", ["created_at"])


def downgrade():
    if inspect(op.get_bind()).has_table("care_patient_handoff_notes"):
        op.drop_table("care_patient_handoff_notes")
