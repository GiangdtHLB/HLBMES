"""transfer_px_request requested_transfer_date

Revision ID: 6855852e132d
Revises: 9ae097c425cd
Create Date: 2026-09-16 08:15:09.246245

Cột mới, nullable — "Ngày đề nghị điều chuyển" (Kho phân xưởng -> Kho công ty), khai lúc
tạo/sửa đề nghị, dùng làm ngày hiệu lực (`ts`) của StockMovement transfer khi Kho công ty duyệt
(yêu cầu người dùng 2026-09-16: áp dụng cùng cơ chế cho cả 2 chiều điều chuyển), mirror
transfer_kcpx_request.requested_transfer_date (migration 9ae097c425cd)."""
from alembic import op
import sqlalchemy as sa


revision = '6855852e132d'
down_revision = '9ae097c425cd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('transfer_px_request') as batch_op:
        batch_op.add_column(sa.Column('requested_transfer_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('transfer_px_request') as batch_op:
        batch_op.drop_column('requested_transfer_date')
