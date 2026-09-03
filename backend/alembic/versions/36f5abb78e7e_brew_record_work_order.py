"""brew_record_work_order

Revision ID: 36f5abb78e7e
Revises: bfd9533a2e21
Create Date: 2026-08-27 14:40:43.238953

Nối "Điều độ" (Work Order) vào luồng Nấu thật — "Phát mẻ" giờ tạo mã nấu/mẻ thật
(BrewRecord/BrewBatch) thay vì BatchExecution (module "Mẻ sản xuất" cũ, không đổi gì).
Thêm `brew_record.work_order_id` (nullable, mirror pattern brew_order_id/production_order_id
đã có) — 1 WorkOrder ↔ tối đa 1 mã nấu, validate ở services/workorders.py::dispatch. Không FK
constraint thật (mirror cách bfd9533a2e21 thêm production_order.beer_type_id — SQLite không
enforce FK bằng ALTER TABLE ADD COLUMN, chỉ cần cột + index cho query/join).

Autogenerate lúc tạo migration này bắt luôn 1 loạt lệch schema không liên quan tích lũy từ các
migration cũ trên SQLite dev (đổi kiểu cột, thêm FK/index rải rác nhiều bảng khác) — đã bỏ hết,
CHỈ giữ đúng thay đổi của migration này.
"""
from alembic import op
import sqlalchemy as sa


revision = '36f5abb78e7e'
down_revision = 'bfd9533a2e21'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_record', sa.Column('work_order_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_brew_record_work_order_id', 'brew_record', ['work_order_id'])


def downgrade() -> None:
    op.drop_index('ix_brew_record_work_order_id', table_name='brew_record')
    op.drop_column('brew_record', 'work_order_id')
