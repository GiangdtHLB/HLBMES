"""ai job queue (bảng job)

Revision ID: a1b2c3d4e5f6
Revises: 89f74fef30e3
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '89f74fef30e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'job',
        sa.Column('job_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=255), nullable=False, server_default='queued'),
        sa.Column('params', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('job_id'),
    )
    op.create_index(op.f('ix_job_kind'), 'job', ['kind'], unique=False)
    op.create_index(op.f('ix_job_status'), 'job', ['status'], unique=False)
    op.create_index(op.f('ix_job_created_by'), 'job', ['created_by'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_job_created_by'), table_name='job')
    op.drop_index(op.f('ix_job_status'), table_name='job')
    op.drop_index(op.f('ix_job_kind'), table_name='job')
    op.drop_table('job')
