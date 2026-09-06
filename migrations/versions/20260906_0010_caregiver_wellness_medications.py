"""caregiver wellness and medication timing records

Revision ID: 20260906_0010
Revises: 20260906_0009
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260906_0010"
down_revision = "20260906_0009"
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def upgrade():
    inspector = inspect(op.get_bind())
    uuid = _uuid_type()
    if not inspector.has_table("caregiver_wellness_check_ins"):
        op.create_table(
            "caregiver_wellness_check_ins",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("feeling", sa.String(20), nullable=False),
            sa.Column("sleep_minutes", sa.Integer(), nullable=True),
            sa.Column("broken_night", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("note", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_caregiver_wellness_check_ins_user_id", "caregiver_wellness_check_ins", ["user_id"])
        op.create_index("ix_caregiver_wellness_check_ins_created_at", "caregiver_wellness_check_ins", ["created_at"])
    if not inspector.has_table("care_patient_medication_schedules"):
        op.create_table(
            "care_patient_medication_schedules",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("patient_id", uuid, sa.ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by_user_id", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("instructions", sa.String(255), nullable=True),
            sa.Column("window_start", sa.String(5), nullable=False),
            sa.Column("window_end", sa.String(5), nullable=False),
            sa.Column("clinician_confirmed", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_care_patient_medication_schedules_patient_id", "care_patient_medication_schedules", ["patient_id"])
    if not inspector.has_table("care_patient_medication_logs"):
        op.create_table(
            "care_patient_medication_logs",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("patient_id", uuid, sa.ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("schedule_id", uuid, sa.ForeignKey("care_patient_medication_schedules.id", ondelete="CASCADE"), nullable=False),
            sa.Column("logged_by_user_id", uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("note", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_care_patient_medication_logs_patient_id", "care_patient_medication_logs", ["patient_id"])
        op.create_index("ix_care_patient_medication_logs_schedule_id", "care_patient_medication_logs", ["schedule_id"])
        op.create_index("ix_care_patient_medication_logs_occurred_at", "care_patient_medication_logs", ["occurred_at"])


def downgrade():
    inspector = inspect(op.get_bind())
    for table in ("care_patient_medication_logs", "care_patient_medication_schedules", "caregiver_wellness_check_ins"):
        if inspector.has_table(table):
            op.drop_table(table)
