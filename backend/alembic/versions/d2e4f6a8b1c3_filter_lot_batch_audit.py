"""filter_lot_batch_audit

batch_filter_lot_batch: thêm started_at (tách khỏi created_at) + created_by/updated_by/
updated_at — audit trail "người nhập/ngày giờ nhập" + "người sửa/ngày giờ sửa" cho từng mẻ lọc
(yêu cầu người dùng 2026-10-11).

Trước đây created_at vừa đóng vai trò mốc tạo bản ghi, VỪA bị finish_filter_lot_batch ghi đè
làm hiển thị cột "Bắt đầu" (qua tham số `started_at`, xem services/batch_pipeline.py — "không
truyền thì giữ nguyên created_at") — nghĩa là created_at KHÔNG phải mốc tạo bản ghi bất biến,
không dùng được làm "ngày giờ nhập" đáng tin cậy, và không có field nào ghi lại AI đã tạo/sửa.
Tách "Bắt đầu" (business, có thể sửa) sang cột `started_at` riêng — backfill từ created_at hiện
có để cột "Bắt đầu" hiển thị không đổi cho dữ liệu cũ; created_at từ nay là mốc tạo bản ghi THẬT,
không còn bị ghi đè.

created_by/updated_by/updated_at: NULL cho dữ liệu lịch sử (chưa từng ghi nhận ai tạo/sửa trước
migration này) — chấp nhận, không suy ngược được từ dữ liệu cũ.

Revision ID: d2e4f6a8b1c3
Revises: c55dce88de16
Create Date: 2026-10-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd2e4f6a8b1c3'
down_revision = 'c55dce88de16'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_filter_lot_batch') as batch_op:
        batch_op.add_column(sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('created_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('updated_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("UPDATE batch_filter_lot_batch SET started_at = created_at"))


def downgrade() -> None:
    with op.batch_alter_table('batch_filter_lot_batch') as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('updated_by')
        batch_op.drop_column('created_by')
        batch_op.drop_column('started_at')
