"""Add optional caregiver nap duration; existing logs remain valid."""
from alembic import op
import sqlalchemy as sa
revision = "20261007_0011"
down_revision = "20260906_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("care_patient_events", sa.Column("duration_min", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("care_patient_events", "duration_min")
