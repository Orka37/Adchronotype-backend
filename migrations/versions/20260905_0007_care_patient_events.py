"""care patient event logging

Revision ID: 20260905_0007
Revises: 20260904_0006
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260905_0007"
down_revision = "20260904_0006"
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def upgrade():
    inspector = inspect(op.get_bind())
    if inspector.has_table("care_patient_events"):
        return
    uuid = _uuid_type()
    op.create_table(
        "care_patient_events",
        sa.Column("id", uuid, primary_key=True, nullable=False),
        sa.Column("patient_id", uuid, sa.ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("logged_by_user_id", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("event_type IN ('slept', 'woke', 'napped', 'agitated', 'other')", name="ck_care_patient_event_type"),
    )
    op.create_index("ix_care_patient_events_patient_id", "care_patient_events", ["patient_id"])
    op.create_index("ix_care_patient_events_logged_by_user_id", "care_patient_events", ["logged_by_user_id"])
    op.create_index("ix_care_patient_events_event_time", "care_patient_events", ["event_time"])


def downgrade():
    if inspect(op.get_bind()).has_table("care_patient_events"):
        op.drop_table("care_patient_events")
