"""filter_order_effective_at

Thêm "Ngày giờ tạo lệnh" (effective_at) cho batch_filter_order — mốc HIỆU LỰC người lập Lệnh lọc
tự chọn (có thể lùi ngày), KHÁC created_at (luôn là lúc bấm "Tạo lệnh lọc" thật, chỉ hiển thị,
không sửa được) — mirror phân biệt StockMovement.ts (ngày hiệu lực) / created_at (ngày tạo phiếu
thật) đã dùng ở nơi khác trong hệ thống. Dùng để tra tồn vật tư dự kiến TẠI ĐÚNG thời điểm đó thay
vì tồn hiện tại — thiếu tồn tại thời điểm này KHÔNG chặn tạo lệnh nữa, chỉ cảnh báo (yêu cầu người
dùng 2026-09-30).

Nullable (không backfill): lệnh tạo TRƯỚC migration này không có giá trị — ứng dụng tự hiểu
effective_at=None nghĩa là dùng created_at.

Revision ID: 1df6797ac310
Revises: 3e4f49df5828
Create Date: 2026-09-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '1df6797ac310'
down_revision = '3e4f49df5828'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_filter_order') as batch_op:
        batch_op.add_column(sa.Column('effective_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('batch_filter_order') as batch_op:
        batch_op.drop_column('effective_at')
