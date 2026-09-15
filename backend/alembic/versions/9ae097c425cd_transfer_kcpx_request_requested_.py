"""transfer_kcpx_request requested_transfer_date

Revision ID: 9ae097c425cd
Revises: a8201554dd44
Create Date: 2026-09-16 01:00:42.508835

Cột mới, nullable — "Ngày đề nghị điều chuyển" (Kho công ty -> Kho phân xưởng), khai lúc
tạo/sửa đề nghị, dùng làm ngày hiệu lực (`ts`) của StockMovement transfer khi duyệt (yêu cầu
người dùng 2026-09-16: "vật tư vào kho phân xưởng ... chính là ngày đề nghị điều chuyển"),
mirror material_request.requested_receipt_date (migration c749b25aba5c)."""
from alembic import op
import sqlalchemy as sa


revision = '9ae097c425cd'
down_revision = 'a8201554dd44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('transfer_kcpx_request') as batch_op:
        batch_op.add_column(sa.Column('requested_transfer_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('transfer_kcpx_request') as batch_op:
        batch_op.drop_column('requested_transfer_date')
