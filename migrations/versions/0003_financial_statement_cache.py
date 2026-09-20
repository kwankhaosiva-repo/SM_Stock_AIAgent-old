"""Add financial_statement_cache table."""

from alembic import op
import sqlalchemy as sa

revision = '0003_financial_statement_cache'
down_revision = '0002_user_chat_state'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('financial_statement_cache',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol', sa.String(), nullable=False, index=True),
        sa.Column('data_json', sa.Text(), nullable=False),
        sa.Column('source', sa.String(), nullable=False, server_default='yahoo'),
        sa.Column('collected_at', sa.DateTime(), nullable=False, index=True),
    )


def downgrade():
    op.drop_table('financial_statement_cache')
