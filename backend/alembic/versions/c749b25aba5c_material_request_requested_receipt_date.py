"""material_request: thêm requested_receipt_date (ngày đề nghị nhận kho, khác ngày lập phiếu)

Revision ID: c749b25aba5c
Revises: ae7424b8e601
Create Date: 2026-09-14 22:55:00.000000

Cột mới, nullable, không ràng buộc gì — cho phép sửa "Ngày đề nghị nhận kho" trên phiếu đã có
(khác `requested_at` là ngày LẬP phiếu, không sửa). Khi thủ kho công ty duyệt (fulfill), ngày
này được dùng làm `ts` hiệu lực của StockMovement transfer, mirror đúng cách approve_sang_ngang
dùng "Ngày xuất sang ngang" — xem services/warehouse.py::fulfill_request_line/fulfill_all_lines.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c749b25aba5c'
down_revision = 'ae7424b8e601'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('material_request') as batch_op:
        batch_op.add_column(sa.Column('requested_receipt_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('material_request') as batch_op:
        batch_op.drop_column('requested_receipt_date')
