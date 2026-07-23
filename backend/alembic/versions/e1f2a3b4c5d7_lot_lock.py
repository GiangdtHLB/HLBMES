"""khóa lô (locked/locked_by/locked_at) cho chuỗi Nấu-Lên men-Lọc-Chiết

Revision ID: e1f2a3b4c5d7
Revises: d0e1f2a3b4c5
Create Date: 2026-07-19

Thêm locked (bool, default False)/locked_by/locked_at vào 8 bảng: brew_order, brew_record,
brew_batch, ferment_record, filter_master_order, filter_order, filter_record, bottle_record —
xem services/lot_lock.py::lock_lot (KCS "Khóa lô" tại 1 mẻ chiết, khóa toàn bộ chuỗi ngược dòng
đã tạo ra nó qua genealogy.trace_backward + resolve brew_order_id/filter_order_id/master_order_id).
Không backfill dữ liệu.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d7'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None

TABLES = ['brew_order', 'brew_record', 'brew_batch', 'ferment_record',
          'filter_master_order', 'filter_order', 'filter_record', 'bottle_record']


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column(table, sa.Column('locked_by', sa.Unicode(255), nullable=True))
        op.add_column(table, sa.Column('locked_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, 'locked_at')
        op.drop_column(table, 'locked_by')
        op.drop_column(table, 'locked')
