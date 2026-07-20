"""add cognitive test attempt numbers

Revision ID: 20260719_0003
Revises: 20260717_0002
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "20260719_0003"
down_revision = "20260717_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cognitive_tests",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_cognitive_tests_user_attempt",
        "cognitive_tests",
        ["user_id", "attempt_number"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_cognitive_tests_user_attempt", table_name="cognitive_tests")
    op.drop_column("cognitive_tests", "attempt_number")
