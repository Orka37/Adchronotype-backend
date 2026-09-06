"""patient-centered caregiver roles and invitations

Revision ID: 20260904_0006
Revises: 20260817_0005
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260904_0006"
down_revision = "20260817_0005"
branch_labels = None
depends_on = None


def _uuid_type():
    return postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36)


def upgrade():
    inspector = inspect(op.get_bind())
    uuid = _uuid_type()
    if not inspector.has_table("care_patients"):
        op.create_table(
            "care_patients",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("display_name", sa.String(length=100), nullable=False),
            sa.Column("primary_caregiver_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_care_patients_primary_caregiver_id", "care_patients", ["primary_caregiver_id"])

    inspector = inspect(op.get_bind())
    if not inspector.has_table("care_patient_members"):
        op.create_table(
            "care_patient_members",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("patient_id", uuid, sa.ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("granted_by_user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("patient_id", "user_id", name="uq_care_patient_member"),
            sa.CheckConstraint("role IN ('primary', 'helper')", name="ck_care_patient_member_role"),
            sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_care_patient_member_status"),
        )
        op.create_index("ix_care_patient_members_patient_id", "care_patient_members", ["patient_id"])
        op.create_index("ix_care_patient_members_user_id", "care_patient_members", ["user_id"])

    inspector = inspect(op.get_bind())
    if not inspector.has_table("care_patient_invitations"):
        op.create_table(
            "care_patient_invitations",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("patient_id", uuid, sa.ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("invited_by_user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("invitee_user_id", uuid, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("invited_email", sa.String(length=255), nullable=True),
            sa.Column("role", sa.String(length=20), nullable=False, server_default="helper"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("role = 'helper'", name="ck_care_patient_invitation_role"),
            sa.CheckConstraint("status IN ('pending', 'accepted', 'declined', 'cancelled')", name="ck_care_patient_invitation_status"),
            sa.CheckConstraint("invitee_user_id IS NOT NULL OR invited_email IS NOT NULL", name="ck_care_patient_invitation_target"),
        )
        op.create_index("ix_care_patient_invitations_patient_id", "care_patient_invitations", ["patient_id"])
        op.create_index("ix_care_patient_invitations_invitee_user_id", "care_patient_invitations", ["invitee_user_id"])
        op.create_index("ix_care_patient_invitations_invited_email", "care_patient_invitations", ["invited_email"])


def downgrade():
    inspector = inspect(op.get_bind())
    if inspector.has_table("care_patient_invitations"):
        op.drop_table("care_patient_invitations")
    inspector = inspect(op.get_bind())
    if inspector.has_table("care_patient_members"):
        op.drop_table("care_patient_members")
    inspector = inspect(op.get_bind())
    if inspector.has_table("care_patients"):
        op.drop_table("care_patients")
