"""Add users.chat_state for persistent chat state across Cloud Run instances."""

from alembic import op
import sqlalchemy as sa

revision = '0002_user_chat_state'
down_revision = '0001_report_workflow'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('chat_state', sa.String(), nullable=True))


def downgrade():
    op.drop_column('users', 'chat_state')
