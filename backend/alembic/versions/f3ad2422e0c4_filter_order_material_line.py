"""Lệnh lọc — thêm dòng vật tư (chất trợ lọc) với snapshot tồn kho

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-07-17

- filter_order_material_line: 1 dòng vật tư (chọn từ Danh mục vật tư) dùng cho lệnh lọc —
  tồn kho công ty/phân xưởng được chụp lại (snapshot) ngay lúc lập lệnh, mirror
  brew_order_material_line.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3ad2422e0c4'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'filter_order_material_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('material_id', sa.Unicode(length=64), nullable=False),
        sa.Column('material_name', sa.Unicode(length=255), nullable=True),
        sa.Column('uom', sa.Unicode(length=64), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('stock_company_snapshot', sa.Float(), nullable=True),
        sa.Column('stock_workshop_snapshot', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['filter_order_id'], ['filter_order.filter_order_id']),
        sa.ForeignKeyConstraint(['material_id'], ['material.material_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_filter_order_material_line_filter_order_id'), 'filter_order_material_line', ['filter_order_id'])
    op.create_index(op.f('ix_filter_order_material_line_material_id'), 'filter_order_material_line', ['material_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_filter_order_material_line_material_id'), table_name='filter_order_material_line')
    op.drop_index(op.f('ix_filter_order_material_line_filter_order_id'), table_name='filter_order_material_line')
    op.drop_table('filter_order_material_line')
