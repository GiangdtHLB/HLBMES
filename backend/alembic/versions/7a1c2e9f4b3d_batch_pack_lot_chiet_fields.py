"""batch_pack_lot_chiet_fields

Revision ID: 7a1c2e9f4b3d
Revises: 18153f3ab494
Create Date: 2026-08-31 00:00:00.000000

Thêm from_bbt/pack_date vào batch_pack_lot (mirror BottleRecord.from_bbt/bottle_date — chọn
tank BBT nào đi chiết + ngày giờ bắt đầu chiết) + bảng batch_pack_lot_material_usage (mirror
BottleMaterialUsage — NVL cấp cho chiết, VD CO2/hóa chất vệ sinh).
"""
from alembic import op
import sqlalchemy as sa


revision = '7a1c2e9f4b3d'
down_revision = '18153f3ab494'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_pack_lot', sa.Column('from_bbt', sa.Unicode(length=255), nullable=True))
    op.create_index('ix_batch_pack_lot_from_bbt', 'batch_pack_lot', ['from_bbt'])
    op.add_column('batch_pack_lot', sa.Column('pack_date', sa.DateTime(), nullable=True))
    op.execute("UPDATE batch_pack_lot SET pack_date = created_at WHERE pack_date IS NULL")

    op.create_table(
        'batch_pack_lot_material_usage',
        sa.Column('usage_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('pack_lot_id', sa.Unicode(length=64), nullable=False),
        sa.Column('lot_id', sa.Unicode(length=64), nullable=True),
        sa.Column('movement_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_date', sa.DateTime(), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_batch_pack_lot_material_usage_pack_lot_id', 'batch_pack_lot_material_usage', ['pack_lot_id'])
    op.create_index('ix_batch_pack_lot_material_usage_lot_id', 'batch_pack_lot_material_usage', ['lot_id'])


def downgrade() -> None:
    op.drop_index('ix_batch_pack_lot_material_usage_lot_id', table_name='batch_pack_lot_material_usage')
    op.drop_index('ix_batch_pack_lot_material_usage_pack_lot_id', table_name='batch_pack_lot_material_usage')
    op.drop_table('batch_pack_lot_material_usage')
    op.drop_column('batch_pack_lot', 'pack_date')
    op.drop_index('ix_batch_pack_lot_from_bbt', table_name='batch_pack_lot')
    op.drop_column('batch_pack_lot', 'from_bbt')
