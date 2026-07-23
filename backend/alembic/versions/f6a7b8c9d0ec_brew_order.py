"""Lệnh nấu (Brew Production Order) + liên kết bắt buộc từ mã nấu

Revision ID: f6a7b8c9d0ec
Revises: e5f6a7b8c9db
Create Date: 2026-07-15

- brew_order: lệnh nấu — mẫu giấy "LỆNH NẤU BIA KIÊM PHIẾU XUẤT KHO" (chỉ giữ phần lệnh).
- brew_order_material_line: dòng Định mức NVL, kèm snapshot tồn 2 kho lúc lập phiếu.
- brew_record.brew_order_id: liên kết 1 mã nấu <-> đúng 1 lệnh nấu (bắt buộc ở tầng schema,
  nullable ở DB để không phá dữ liệu/test cũ).
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0ec'
down_revision = 'e5f6a7b8c9db'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'brew_order',
        sa.Column('brew_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('issued_by', sa.Unicode(length=255), nullable=True),
        sa.Column('executor_unit', sa.Unicode(length=255), nullable=True),
        sa.Column('warehouse_keeper', sa.Unicode(length=255), nullable=True),
        sa.Column('product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('product_desc', sa.UnicodeText(), nullable=True),
        sa.Column('planned_batch_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('planned_volume_l', sa.Float(), nullable=False, server_default='0'),
        sa.Column('bx_min', sa.Float(), nullable=True),
        sa.Column('bx_max', sa.Float(), nullable=True),
        sa.Column('reference_note', sa.UnicodeText(), nullable=True),
        sa.Column('tank_lm', sa.Unicode(length=255), nullable=True),
        sa.Column('batch_range_from', sa.Integer(), nullable=True),
        sa.Column('batch_range_to', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('safety_note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.product_id']),
        sa.PrimaryKeyConstraint('brew_order_id'),
    )
    op.create_index(op.f('ix_brew_order_order_code'), 'brew_order', ['order_code'], unique=True)
    op.create_index(op.f('ix_brew_order_product_id'), 'brew_order', ['product_id'], unique=False)

    op.create_table(
        'brew_order_material_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('stt_label', sa.Unicode(length=16), nullable=True),
        sa.Column('is_header', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('material_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=True),
        sa.Column('uom', sa.Unicode(length=64), nullable=True),
        sa.Column('qty_per_batch', sa.Float(), nullable=True),
        sa.Column('qty_total', sa.Float(), nullable=True),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('stock_company_snapshot', sa.Float(), nullable=True),
        sa.Column('stock_workshop_snapshot', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['brew_order_id'], ['brew_order.brew_order_id']),
        sa.ForeignKeyConstraint(['material_id'], ['material.material_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_brew_order_material_line_brew_order_id'), 'brew_order_material_line', ['brew_order_id'], unique=False)

    op.add_column('brew_record', sa.Column('brew_order_id', sa.Unicode(length=64), nullable=True))
    op.create_index(op.f('ix_brew_record_brew_order_id'), 'brew_record', ['brew_order_id'], unique=False)
    with op.batch_alter_table('brew_record') as batch_op:
        batch_op.create_foreign_key('fk_brew_record_brew_order_id', 'brew_order', ['brew_order_id'], ['brew_order_id'])


def downgrade() -> None:
    with op.batch_alter_table('brew_record') as batch_op:
        batch_op.drop_constraint('fk_brew_record_brew_order_id', type_='foreignkey')
    op.drop_index(op.f('ix_brew_record_brew_order_id'), table_name='brew_record')
    op.drop_column('brew_record', 'brew_order_id')
    op.drop_index(op.f('ix_brew_order_material_line_brew_order_id'), table_name='brew_order_material_line')
    op.drop_table('brew_order_material_line')
    op.drop_index(op.f('ix_brew_order_product_id'), table_name='brew_order')
    op.drop_index(op.f('ix_brew_order_order_code'), table_name='brew_order')
    op.drop_table('brew_order')
