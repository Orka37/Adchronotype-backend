"""initial schema

Revision ID: 20260711_0001
Revises:
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def _uuid_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def _has_table(name):
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _create_index(name, table, columns, unique=False):
    bind = op.get_bind()
    existing = {idx["name"] for idx in sa.inspect(bind).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    uuid = _uuid_type()

    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("first_name", sa.String(100), nullable=False),
            sa.Column("last_name", sa.String(100), nullable=False),
            sa.Column("username", sa.String(50), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("username"),
            sa.UniqueConstraint("email"),
        )
        _create_index("ix_users_username", "users", ["username"], unique=True)
        _create_index("ix_users_email", "users", ["email"], unique=True)

    if not _has_table("refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token", sa.Text(), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("token"),
        )
        _create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    if not _has_table("predictions"):
        op.create_table(
            "predictions",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("age", sa.Integer(), nullable=False),
            sa.Column("bmi", sa.Float(), nullable=False),
            sa.Column("sleep_duration", sa.Float(), nullable=False),
            sa.Column("sleep_time", sa.String(10), nullable=False),
            sa.Column("wake_time", sa.String(10), nullable=False),
            sa.Column("chronotype", sa.String(50), nullable=False),
            sa.Column("ethnicity", sa.String(50), nullable=False),
            sa.Column("family_history", sa.String(10), nullable=False),
            sa.Column("prediction_value", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        _create_index("ix_predictions_user_id", "predictions", ["user_id"])

    if not _has_table("sleep_logs"):
        op.create_table(
            "sleep_logs",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("sleep_time", sa.String(10), nullable=False),
            sa.Column("wake_time", sa.String(10), nullable=False),
            sa.Column("duration_hours", sa.Float(), nullable=False),
            sa.Column("quality_score", sa.Integer(), nullable=False),
            sa.Column("awakenings", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("logged_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        _create_index("ix_sleep_logs_user_id", "sleep_logs", ["user_id"])

    if not _has_table("cognitive_tests"):
        op.create_table(
            "cognitive_tests",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("test_type", sa.String(50), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("unit", sa.String(20), nullable=False),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("tested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        _create_index("ix_cognitive_tests_user_id", "cognitive_tests", ["user_id"])

    if not _has_table("caregiver_links"):
        op.create_table(
            "caregiver_links",
            sa.Column("id", uuid, primary_key=True, nullable=False),
            sa.Column("patient_id", uuid, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("caregiver_id", uuid, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("invited_email", sa.String(255), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        _create_index("ix_caregiver_links_patient_id", "caregiver_links", ["patient_id"])
    elif op.get_bind().dialect.name == "postgresql":
        op.alter_column("caregiver_links", "caregiver_id", existing_type=uuid, nullable=True)


def downgrade():
    for table in [
        "caregiver_links",
        "cognitive_tests",
        "sleep_logs",
        "predictions",
        "refresh_tokens",
        "users",
    ]:
        if _has_table(table):
            op.drop_table(table)
