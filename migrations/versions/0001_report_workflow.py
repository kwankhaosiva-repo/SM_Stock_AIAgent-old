"""Add auditable report workflow tables."""

from alembic import op
import sqlalchemy as sa

revision = '0001_report_workflow'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('market_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('symbol', sa.String(), nullable=False, index=True),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('data_json', sa.Text(), nullable=False),
        sa.Column('collected_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False, index=True),
    )
    op.create_table('source_documents',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('snapshot_id', sa.Integer(), sa.ForeignKey('market_snapshots.id'), nullable=False, index=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('published_at', sa.String(), nullable=True),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
    )
    op.create_table('analysis_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True, index=True),
        sa.Column('symbol', sa.String(), nullable=False, index=True),
        sa.Column('snapshot_id', sa.Integer(), sa.ForeignKey('market_snapshots.id'), nullable=True),
        sa.Column('status', sa.String(), nullable=False, index=True),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_table('agent_outputs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('analysis_run_id', sa.Integer(), sa.ForeignKey('analysis_runs.id'), nullable=False, index=True),
        sa.Column('agent_name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('output_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('report_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('analysis_run_id', sa.Integer(), sa.ForeignKey('analysis_runs.id'), nullable=True),
        sa.Column('idempotency_key', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, index=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('idempotency_key', name='uq_report_delivery_idempotency_key'),
    )


def downgrade():
    op.drop_table('report_deliveries')
    op.drop_table('agent_outputs')
    op.drop_table('analysis_runs')
    op.drop_table('source_documents')
    op.drop_table('market_snapshots')
