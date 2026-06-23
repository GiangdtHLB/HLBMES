"""ISA-88 procedural (recipe_version.procedure + batch_phase_run)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recipe_version',
                  sa.Column('procedure', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.create_table(
        'batch_phase_run',
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('batch_id', sa.String(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unit_class', sa.String(), nullable=True),
        sa.Column('up_name', sa.String(), nullable=False),
        sa.Column('op_name', sa.String(), nullable=False),
        sa.Column('phase_name', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False, server_default='running'),
        sa.Column('params', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('values', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('operator', sa.String(), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['batch_id'], ['batch_execution.batch_id']),
        sa.PrimaryKeyConstraint('run_id'),
    )
    op.create_index(op.f('ix_batch_phase_run_batch_id'), 'batch_phase_run', ['batch_id'], unique=False)
    op.create_index(op.f('ix_batch_phase_run_state'), 'batch_phase_run', ['state'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_batch_phase_run_state'), table_name='batch_phase_run')
    op.drop_index(op.f('ix_batch_phase_run_batch_id'), table_name='batch_phase_run')
    op.drop_table('batch_phase_run')
    op.drop_column('recipe_version', 'procedure')
