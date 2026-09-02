"""filter_lot_materials_fifo_reason

Revision ID: de4c63ff7ee4
Revises: 9d0ebc9999e9
Create Date: 2026-09-01 00:00:00.000000

- batch_pack_lot_material_usage.reason — bắt buộc khi fifo_ok=False (mirror DispenseLine.reason).
- batch_filter_lot_material_usage (mới) — NVL dùng cho lô lọc, mirror batch_pack_lot_material_usage.
Yêu cầu người dùng 2026-09-01.
"""
from alembic import op
import sqlalchemy as sa


revision = 'de4c63ff7ee4'
down_revision = '9d0ebc9999e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_pack_lot_material_usage') as batch_op:
        batch_op.add_column(sa.Column('reason', sa.UnicodeText(), nullable=True))

    op.create_table(
        'batch_filter_lot_material_usage',
        sa.Column('usage_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('filter_lot_id', sa.Unicode(length=64), nullable=False),
        sa.Column('lot_id', sa.Unicode(length=64), nullable=True),
        sa.Column('movement_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=True),
        sa.Column('reason', sa.UnicodeText(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_batch_filter_lot_material_usage_filter_lot_id',
                    'batch_filter_lot_material_usage', ['filter_lot_id'])
    op.create_index('ix_batch_filter_lot_material_usage_lot_id',
                    'batch_filter_lot_material_usage', ['lot_id'])


def downgrade() -> None:
    op.drop_index('ix_batch_filter_lot_material_usage_lot_id', table_name='batch_filter_lot_material_usage')
    op.drop_index('ix_batch_filter_lot_material_usage_filter_lot_id', table_name='batch_filter_lot_material_usage')
    op.drop_table('batch_filter_lot_material_usage')

    with op.batch_alter_table('batch_pack_lot_material_usage') as batch_op:
        batch_op.drop_column('reason')
