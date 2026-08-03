"""Điều chuyển kho công ty: tách 2 chiều PX→CT (duyệt trước khi chuyển) và CT→Nhà máy khác

Revision ID: a1c2d3e4f5b8
Revises: 6f7a8b9c0d1e
Create Date: 2026-08-02

- factory_location: danh mục nhà máy khác — đích của Điều chuyển Kho công ty → Nhà máy khác.
- transfer_px_request: đề nghị điều chuyển Kho phân xưởng → Kho công ty — CHƯA động tồn kho
  lúc tạo, chỉ khi Thủ kho công ty duyệt mới thật sự chuyển; sau khi duyệt chỉ ADMIN hoàn tác.
- stock_movement: thêm destination_factory_id/approved_by/approved_at (chỉ dùng cho
  mode="dieu_chuyen_nha_may" — Điều chuyển Kho công ty → Nhà máy khác, duyệt bởi Trưởng phòng
  Kế hoạch, sau khi duyệt chỉ ADMIN hoàn tác được qua undo_issue()).
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1c2d3e4f5b8'
down_revision = '6f7a8b9c0d1e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'factory_location',
        sa.Column('factory_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('address', sa.Unicode(length=255), nullable=True),
        sa.Column('contact', sa.Unicode(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('factory_id'),
    )
    op.create_index('ix_factory_location_code', 'factory_location', ['code'], unique=True)

    with op.batch_alter_table('stock_movement', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('destination_factory_id', sa.Unicode(length=64),
            sa.ForeignKey('factory_location.factory_id', name='fk_stock_movement_destination_factory_id_factory_location'),
            nullable=True))
        batch_op.add_column(sa.Column('approved_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'transfer_px_request',
        sa.Column('request_id', sa.Unicode(length=64), nullable=False),
        sa.Column('request_code', sa.Unicode(length=64), nullable=False),
        sa.Column('lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False, server_default='kg'),
        sa.Column('reason', sa.UnicodeText(), nullable=True),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='pending'),
        sa.Column('movement_id', sa.Unicode(length=64), sa.ForeignKey('stock_movement.movement_id'), nullable=True),
        sa.Column('reversed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by', sa.Unicode(length=255), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reject_reason', sa.UnicodeText(), nullable=True),
        sa.PrimaryKeyConstraint('request_id'),
    )
    op.create_index('ix_transfer_px_request_request_code', 'transfer_px_request', ['request_code'], unique=True)
    op.create_index('ix_transfer_px_request_lot_id', 'transfer_px_request', ['lot_id'])
    op.create_index('ix_transfer_px_request_status', 'transfer_px_request', ['status'])


def downgrade() -> None:
    op.drop_table('transfer_px_request')
    op.drop_column('stock_movement', 'approved_at')
    op.drop_column('stock_movement', 'approved_by')
    op.drop_column('stock_movement', 'destination_factory_id')
    op.drop_table('factory_location')
