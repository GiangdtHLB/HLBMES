"""production order material line (SL lay Kho cong ty/phan xuong)

Revision ID: afe54be711b7
Revises: 5520c402202e
Create Date: 2026-08-21 09:14:33.264404

Lệnh SX (ERP) mirror tính năng "Xem NVL (đủ/thiếu tồn)" tương tác của Lệnh nấu — cho sửa lại
SL lấy tại Kho công ty/phân xưởng + chọn thành viên Nhóm vật tư thay thế trước khi lưu, rồi
LƯU LẠI (snapshot, không phải preview sống) để in đúng số đã chọn — mirror
brew_order_material_line (xem alembic f6a7b8c9d0ec + a7c1b2d3e4f8), thêm sẵn
member_qty_snapshot/qty_from_company/qty_from_workshop ngay từ đầu (không cần migration nối
thêm sau như brew_order_material_line).
"""
from alembic import op
import sqlalchemy as sa


revision = 'afe54be711b7'
down_revision = '5520c402202e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'production_order_material_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('stt_label', sa.Unicode(length=16), nullable=True),
        sa.Column('is_header', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('material_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=True),
        sa.Column('material_group_code', sa.Unicode(length=64), nullable=True),
        sa.Column('member_qty_snapshot', sa.JSON(), nullable=True),
        sa.Column('uom', sa.Unicode(length=64), nullable=True),
        sa.Column('qty_per_batch', sa.Float(), nullable=True),
        sa.Column('qty_total', sa.Float(), nullable=True),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('stock_company_snapshot', sa.Float(), nullable=True),
        sa.Column('stock_workshop_snapshot', sa.Float(), nullable=True),
        sa.Column('qty_from_company', sa.Float(), nullable=True),
        sa.Column('qty_from_workshop', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['production_order.order_id']),
        sa.ForeignKeyConstraint(['material_id'], ['material.material_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_production_order_material_line_order_id'), 'production_order_material_line', ['order_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_production_order_material_line_order_id'), table_name='production_order_material_line')
    op.drop_table('production_order_material_line')
