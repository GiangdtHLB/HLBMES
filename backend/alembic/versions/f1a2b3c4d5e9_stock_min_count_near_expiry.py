"""Kho NVL: cảnh báo tồn tối thiểu + kiểm kê định kỳ; Kho TP: bia cận date

Revision ID: f1a2b3c4d5e9
Revises: d0e1f2a3b4c6
Create Date: 2026-07-22

- material.stock_min (Float, nullable): ngưỡng tồn tối thiểu — vượt dưới mức này thì
  stock_on_hand/inventory_report trả low_stock=True để cảnh báo (Kho NVL).
- stock_count/stock_count_line: phiếu kiểm kê định kỳ (header+lines) đối chiếu tồn hệ
  thống (MaterialLot.quantity) với tồn thực tế đếm tại kho.
- finished_goods_unit.is_near_expiry (Boolean): đánh dấu vỉ/keg đến từ "Nhập bia cận date".
- near_expiry_entry: lịch sử riêng cho nhập/xuất bia cận date (Kho TP).
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e9'
down_revision = 'd0e1f2a3b4c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('material', sa.Column('stock_min', sa.Float(), nullable=True))

    op.create_table(
        'stock_count',
        sa.Column('count_id', sa.Unicode(length=64), nullable=False),
        sa.Column('count_code', sa.Unicode(length=64), nullable=False),
        sa.Column('location', sa.Unicode(length=255), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='draft'),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('posted_by', sa.Unicode(length=255), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('count_id'),
    )
    op.create_index('ix_stock_count_count_code', 'stock_count', ['count_code'], unique=True)
    op.create_index('ix_stock_count_status', 'stock_count', ['status'])

    op.create_table(
        'stock_count_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('count_id', sa.Unicode(length=64), sa.ForeignKey('stock_count.count_id'), nullable=False),
        sa.Column('material_id', sa.Unicode(length=64), sa.ForeignKey('material.material_id'), nullable=False),
        sa.Column('lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=False),
        sa.Column('system_qty', sa.Float(), nullable=False),
        sa.Column('counted_qty', sa.Float(), nullable=True),
        sa.Column('uom', sa.Unicode(length=255), nullable=False, server_default='kg'),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index('ix_stock_count_line_count_id', 'stock_count_line', ['count_id'])
    op.create_index('ix_stock_count_line_material_id', 'stock_count_line', ['material_id'])
    op.create_index('ix_stock_count_line_lot_id', 'stock_count_line', ['lot_id'])

    op.add_column('finished_goods_unit', sa.Column('is_near_expiry', sa.Boolean(), nullable=False,
                                                    server_default=sa.false()))
    op.create_index('ix_finished_goods_unit_is_near_expiry', 'finished_goods_unit', ['is_near_expiry'])

    op.create_table(
        'near_expiry_entry',
        sa.Column('entry_id', sa.Unicode(length=64), nullable=False),
        sa.Column('direction', sa.Unicode(length=16), nullable=False),
        sa.Column('product_name', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_code', sa.Unicode(length=64), nullable=True),
        sa.Column('unit_type', sa.Unicode(length=16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('declared_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('bottle_id', sa.Unicode(length=64), sa.ForeignKey('bottle_record.bottle_id'), nullable=True),
        sa.Column('shipment_id', sa.Unicode(length=64), sa.ForeignKey('shipment.shipment_id'), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('entry_id'),
    )
    op.create_index('ix_near_expiry_entry_direction', 'near_expiry_entry', ['direction'])
    op.create_index('ix_near_expiry_entry_bottle_id', 'near_expiry_entry', ['bottle_id'])
    op.create_index('ix_near_expiry_entry_shipment_id', 'near_expiry_entry', ['shipment_id'])


def downgrade() -> None:
    op.drop_table('near_expiry_entry')
    op.drop_index('ix_finished_goods_unit_is_near_expiry', table_name='finished_goods_unit')
    op.drop_column('finished_goods_unit', 'is_near_expiry')
    op.drop_table('stock_count_line')
    op.drop_table('stock_count')
    op.drop_column('material', 'stock_min')
