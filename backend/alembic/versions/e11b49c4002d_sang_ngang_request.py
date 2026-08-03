"""Xuất sang ngang: Kho công ty nhận hàng nhưng đích thực sự là Kho phân xưởng

Revision ID: e11b49c4002d
Revises: f3a4b5c6d7e8
Create Date: 2026-08-03

- sang_ngang_request: đề nghị "Xuất sang ngang" — lô được receive() bình thường vào Kho công
  ty (tăng tồn công ty, ghi StockMovement type=receipt), CHƯA chuyển vị trí; chỉ khi Thủ kho
  phân xưởng duyệt (approve_sang_ngang) mới thật sự gọi transfer() đổi lô sang Kho phân xưởng.
  Nếu vật tư có chỉ tiêu chất lượng bắt buộc, phân xưởng không duyệt được cho tới khi KCS duyệt
  xong (lot.status rời ON_HOLD).
"""
from alembic import op
import sqlalchemy as sa

revision = 'e11b49c4002d'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sang_ngang_request',
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
    op.create_index('ix_sang_ngang_request_request_code', 'sang_ngang_request', ['request_code'], unique=True)
    op.create_index('ix_sang_ngang_request_lot_id', 'sang_ngang_request', ['lot_id'])
    op.create_index('ix_sang_ngang_request_status', 'sang_ngang_request', ['status'])


def downgrade() -> None:
    op.drop_table('sang_ngang_request')
