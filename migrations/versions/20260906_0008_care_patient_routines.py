"""care patient routines

Revision ID: 20260906_0008
Revises: 20260905_0007
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260906_0008"
down_revision = "20260905_0007"
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def upgrade():
    if inspect(op.get_bind()).has_table("care_patient_routines"):
        return
    uuid = _uuid_type()
    op.create_table(
        "care_patient_routines",
        sa.Column("id", uuid, primary_key=True, nullable=False),
        sa.Column("patient_id", uuid, sa.ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("usual_bedtime", sa.String(length=5), nullable=False),
        sa.Column("usual_wake_time", sa.String(length=5), nullable=False),
        sa.Column("nap_start_time", sa.String(length=5), nullable=True),
        sa.Column("nap_end_time", sa.String(length=5), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_care_patient_routines_patient_id", "care_patient_routines", ["patient_id"], unique=True)


def downgrade():
    if inspect(op.get_bind()).has_table("care_patient_routines"):
        op.drop_table("care_patient_routines")
