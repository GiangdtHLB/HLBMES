"""qc_group_item_updated_audit

qc_parameter_group_item: thêm updated_by/updated_at — "Người sửa/ngày giờ sửa" cho màn "Chỉ
tiêu trong nhóm" (yêu cầu người dùng 2026-10-14). NULL cho dữ liệu lịch sử (chưa từng ghi nhận
ai sửa trước migration này) — chấp nhận, không suy ngược được từ dữ liệu cũ (tra audit_log thủ
công nếu cần lịch sử cũ).

Revision ID: c39d10057e93
Revises: e0a29816b722
Create Date: 2026-10-14 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c39d10057e93'
down_revision = 'e0a29816b722'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('qc_parameter_group_item') as batch_op:
        batch_op.add_column(sa.Column('updated_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('qc_parameter_group_item') as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('updated_by')
