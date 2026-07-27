"""quality_result.sampled_at — mốc ngày giờ lấy mẫu (nhiều lần) cho CT chính/CT phụ lên men

Revision ID: e644f098d750
Revises: d1e2f3a4b5c7
Create Date: 2026-07-25

Cho phép 1 chỉ tiêu có NHIỀU dòng kết quả theo thời gian (lần 1, lần 2, lần 3...) thay vì
ghi đè tại chỗ như trước — chỉ áp dụng cho stage len_men_chinh/len_men_phu (xem
qc_catalog.MULTI_SAMPLE_STAGES + record_qc_sample). Nullable vì mọi dòng cũ (và mọi stage
khác vẫn ghi đè tại chỗ) không có mốc này — latest_results_by_param dùng
coalesce(sampled_at, recorded_at) để chọn "giá trị mới nhất" nên NULL vẫn hoạt động đúng
như trước (rơi về recorded_at).
"""
from alembic import op
import sqlalchemy as sa

revision = 'e644f098d750'
down_revision = 'd1e2f3a4b5c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('quality_result') as batch_op:
        batch_op.add_column(sa.Column('sampled_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('quality_result') as batch_op:
        batch_op.drop_column('sampled_at')
