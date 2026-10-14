"""Add a stable Google identity; existing passwords remain unchanged."""
from alembic import op
import sqlalchemy as sa
revision = '20261012_0012'
down_revision = '20261007_0011'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('google_subject', sa.String(255), nullable=True))
    op.create_index('uq_users_google_subject', 'users', ['google_subject'], unique=True)


def downgrade():
    op.drop_index('uq_users_google_subject', table_name='users')
    op.drop_column('users', 'google_subject')
