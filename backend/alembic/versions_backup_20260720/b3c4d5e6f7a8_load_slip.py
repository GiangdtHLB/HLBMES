"""Lệnh đóng hàng: Biên bản bàn giao hàng hóa theo xe (LoadSlip/LoadSlipLine)

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-07-15

- load_slip: 1 biên bản bàn giao hàng hóa cho 1 xe, gộp từ file Excel "Lệnh đóng hàng"
  (sheet HL/ĐM), nhóm theo SỐ XE.
- load_slip_line: từng dòng hàng hóa (mỗi cột SKU > 0 trong file) — dòng khuyến mại rời
  (LON/Lốc ... KM) tách riêng is_promo=True.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'load_slip',
        sa.Column('load_slip_id', sa.Unicode(length=64), nullable=False),
        sa.Column('slip_code', sa.Unicode(length=64), nullable=False),
        sa.Column('sheet_type', sa.Unicode(length=16), nullable=False),
        sa.Column('shift_label', sa.Unicode(length=64), nullable=True),
        sa.Column('order_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('vehicle_plate', sa.Unicode(length=64), nullable=False),
        sa.Column('driver_name', sa.Unicode(length=255), nullable=True),
        sa.Column('routes', sa.UnicodeText(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('source_file_name', sa.Unicode(length=255), nullable=True),
        sa.Column('issuer_name', sa.Unicode(length=255), nullable=True),
        sa.Column('issuer_title', sa.Unicode(length=255), nullable=True),
        sa.Column('issuer_dept', sa.Unicode(length=255), nullable=True),
        sa.Column('recipient_name', sa.Unicode(length=255), nullable=True),
        sa.Column('recipient_title', sa.Unicode(length=255), nullable=True),
        sa.Column('recipient_unit', sa.Unicode(length=255), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('load_slip_id'),
    )
    op.create_index(op.f('ix_load_slip_slip_code'), 'load_slip', ['slip_code'], unique=True)
    op.create_index(op.f('ix_load_slip_sheet_type'), 'load_slip', ['sheet_type'], unique=False)
    op.create_index(op.f('ix_load_slip_vehicle_plate'), 'load_slip', ['vehicle_plate'], unique=False)

    op.create_table(
        'load_slip_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('load_slip_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('product_name', sa.Unicode(length=255), nullable=False),
        sa.Column('uom', sa.Unicode(length=64), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('is_promo', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.ForeignKeyConstraint(['load_slip_id'], ['load_slip.load_slip_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_load_slip_line_load_slip_id'), 'load_slip_line', ['load_slip_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_load_slip_line_load_slip_id'), table_name='load_slip_line')
    op.drop_table('load_slip_line')
    op.drop_index(op.f('ix_load_slip_vehicle_plate'), table_name='load_slip')
    op.drop_index(op.f('ix_load_slip_sheet_type'), table_name='load_slip')
    op.drop_index(op.f('ix_load_slip_slip_code'), table_name='load_slip')
    op.drop_table('load_slip')
