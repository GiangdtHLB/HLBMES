"""scheduling (schedule_slot)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'schedule_slot',
        sa.Column('slot_id', sa.Unicode(length=64), nullable=False),
        sa.Column('resource', sa.Unicode(length=255), nullable=False),
        sa.Column('kind', sa.Unicode(length=255), nullable=False, server_default='production'),
        sa.Column('wo_id', sa.Unicode(length=64), nullable=True),
        sa.Column('wo_code', sa.Unicode(length=64), nullable=True),
        sa.Column('product', sa.Unicode(length=255), nullable=True),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='planned'),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('slot_id'),
    )
    op.create_index(op.f('ix_schedule_slot_resource'), 'schedule_slot', ['resource'], unique=False)
    op.create_index(op.f('ix_schedule_slot_wo_id'), 'schedule_slot', ['wo_id'], unique=False)
    op.create_index(op.f('ix_schedule_slot_start_at'), 'schedule_slot', ['start_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_schedule_slot_start_at'), table_name='schedule_slot')
    op.drop_index(op.f('ix_schedule_slot_wo_id'), table_name='schedule_slot')
    op.drop_index(op.f('ix_schedule_slot_resource'), table_name='schedule_slot')
    op.drop_table('schedule_slot')
