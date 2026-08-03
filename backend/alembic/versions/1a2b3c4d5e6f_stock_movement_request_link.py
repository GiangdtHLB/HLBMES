"""Kho NVL: liên kết StockMovement với MaterialRequest/MaterialRequestLine

Revision ID: 1a2b3c4d5e6f
Revises: f4a5b6c7d8e0
Create Date: 2026-08-02

- stock_movement: thêm request_id/request_line_id (FK, nullable) — liên kết trực tiếp giao
  dịch điều chuyển phát sinh từ Đề nghị nhận kho (fulfill_request_line/fulfill_all_lines) tới
  đúng phiếu/dòng đề nghị, thay cho so khớp chuỗi văn bản `reason` (xem
  services/warehouse.py::delete_request_history) vốn dễ vỡ nếu định dạng lý do từng bị sửa tay.
  Giao dịch cũ (tạo trước migration này) sẽ có 2 cột này NULL — delete_request_history vẫn dự
  phòng khớp theo `reason` cho các giao dịch cũ đó.
"""
from alembic import op
import sqlalchemy as sa

revision = '1a2b3c4d5e6f'
down_revision = 'f4a5b6c7d8e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('stock_movement', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('request_id', sa.Unicode(64), nullable=True))
        batch_op.add_column(sa.Column('request_line_id', sa.Unicode(64), nullable=True))
        batch_op.create_foreign_key('fk_stock_movement_request_id', 'material_request',
                                    ['request_id'], ['request_id'])
        batch_op.create_foreign_key('fk_stock_movement_request_line_id', 'material_request_line',
                                    ['request_line_id'], ['line_id'])
    op.create_index('ix_stock_movement_request_id', 'stock_movement', ['request_id'])


def downgrade() -> None:
    op.drop_index('ix_stock_movement_request_id', table_name='stock_movement')
    with op.batch_alter_table('stock_movement', recreate='auto') as batch_op:
        batch_op.drop_constraint('fk_stock_movement_request_line_id', type_='foreignkey')
        batch_op.drop_constraint('fk_stock_movement_request_id', type_='foreignkey')
        batch_op.drop_column('request_line_id')
        batch_op.drop_column('request_id')
