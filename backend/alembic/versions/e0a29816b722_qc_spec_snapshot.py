"""qc_spec_snapshot

Chụp lại (snapshot) danh sách chỉ tiêu chất lượng bắt buộc + ngưỡng (Min/Max) đang cấu hình ở
Danh mục NGAY LÚC TẠO mẻ (tank lên men/lô lọc/lô thành phẩm) — mirror cách required_params_for_
stage() tính "required" nhưng chụp 1 LẦN, lưu cố định vào chính bản ghi, thay vì tra lại Danh
mục SỐNG mỗi lần xem (yêu cầu người dùng 2026-10-13, ca thực tế: Danh mục vừa thêm Min/Max cho
1 chỉ tiêu SAU KHI 1 lô lọc đã ghi nhận giá trị — kết quả cũ hiện "pass" vì lúc ghi chưa có
ngưỡng nào, trong khi bảng hiển thị lại lấy Min/Max HIỆN TẠI, gây hiểu lầm "rõ ràng vượt mà vẫn
pass"). Từ nay: Danh mục sửa ngưỡng chỉ áp dụng cho mẻ MỚI tạo SAU thời điểm sửa — mẻ cũ giữ
nguyên ngưỡng đã chụp lúc tạo, không bị đổi ngược.

3 cột JSON mới, tất cả NULLABLE — NULL nghĩa là bản ghi tạo TRƯỚC migration này (dữ liệu cũ),
qc_catalog.py::stage_qc_status tự nhận biết NULL và tra trực tiếp Danh mục HIỆN TẠI như hành vi
cũ (không có gì để backfill — không có cách nào biết CHÍNH XÁC Danh mục trông thế nào tại đúng
lúc mỗi bản ghi cũ được tạo).
- batch_tank.qc_spec_snapshot: dict {"len_men_chinh": [...], "len_men_phu": [...]} (2 stage
  trên cùng 1 bản ghi).
- batch_filter_lot.qc_spec_snapshot: list (1 stage "loc").
- batch_pack_lot.qc_spec_snapshot: list (1 stage "thanh_pham").

Revision ID: e0a29816b722
Revises: e5f7a9b2c4d6
Create Date: 2026-10-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e0a29816b722'
down_revision = 'e5f7a9b2c4d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_tank') as batch_op:
        batch_op.add_column(sa.Column('qc_spec_snapshot', sa.JSON(), nullable=True))
    with op.batch_alter_table('batch_filter_lot') as batch_op:
        batch_op.add_column(sa.Column('qc_spec_snapshot', sa.JSON(), nullable=True))
    with op.batch_alter_table('batch_pack_lot') as batch_op:
        batch_op.add_column(sa.Column('qc_spec_snapshot', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('batch_pack_lot') as batch_op:
        batch_op.drop_column('qc_spec_snapshot')
    with op.batch_alter_table('batch_filter_lot') as batch_op:
        batch_op.drop_column('qc_spec_snapshot')
    with op.batch_alter_table('batch_tank') as batch_op:
        batch_op.drop_column('qc_spec_snapshot')
