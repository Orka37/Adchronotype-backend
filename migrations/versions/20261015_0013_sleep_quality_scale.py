"""Version sleep quality ratings without converting historical scores."""
from alembic import op
import sqlalchemy as sa
revision = '20261015_0013'
down_revision = '20261012_0012'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sleep_logs', sa.Column('quality_scale', sa.String(20), nullable=False, server_default='legacy_0_21'))


def downgrade():
    # Refuse to erase scale metadata while new ratings exist.
    count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM sleep_logs WHERE quality_scale = 'rating_1_10'")).scalar()
    if count:
        raise RuntimeError('Cannot remove quality scale while 1–10 ratings exist')
    op.drop_column('sleep_logs', 'quality_scale')
