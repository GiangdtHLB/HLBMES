"""brew order production order link

Revision ID: 1825842d838f
Revises: b09abc6c171e
Create Date: 2026-08-24 00:50:24.279250

"Lệnh nấu" (BrewOrder) hồi sinh làm lớp thực thi con của "Lệnh SX (ERP)" (ProductionOrder) —
thêm brew_order.production_order_id (nullable, 1 Lệnh SX chỉ có đúng 1 Lệnh nấu, validate ở
services/brew_order.py::create_order, không CHECK constraint ở DB). Lệnh nấu lịch sử (tạo
trước khi có liên kết này) giữ nguyên NULL, không backfill.
"""
from alembic import op
import sqlalchemy as sa


revision = '1825842d838f'
down_revision = 'b09abc6c171e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_order', sa.Column('production_order_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_brew_order_production_order_id', 'brew_order', ['production_order_id'])


def downgrade() -> None:
    op.drop_index('ix_brew_order_production_order_id', table_name='brew_order')
    op.drop_column('brew_order', 'production_order_id')
