"""pallet.shipped_at — ghi ngày xuất pallet (yêu cầu người dùng 2026-09-20: "thêm cột ngày
nhập kho thành phẩm, ngày xuất" trên màn hình Kho TP/WMS)

Revision ID: 10cacc2b8540
Revises: f7e8d9c0b1a2
Create Date: 2026-09-20

Cột mới, nullable — "ngày nhập kho thành phẩm" đã có sẵn (`pallet.created_at`, ghi lúc pallet
được tạo — luôn trùng thời điểm đưa vào kho vì pallet luôn được tạo kèm đặt vị trí/status ngay).
`shipped_at` ghi thời điểm `ship()` chuyển pallet sang trạng thái "shipped". Dữ liệu cũ (pallet
đã xuất từ trước migration này) để NULL — không có cách nào suy ngược lại đúng thời điểm xuất
thật, không backfill giả."""
from alembic import op
import sqlalchemy as sa

revision = '10cacc2b8540'
down_revision = 'f7e8d9c0b1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('pallet') as batch_op:
        batch_op.add_column(sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('pallet') as batch_op:
        batch_op.drop_column('shipped_at')
