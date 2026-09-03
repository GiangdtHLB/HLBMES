"""batch_pack_lot.lot_no unique theo năm + ebr_snapshot(batch_id, snapshot_version) unique

Revision ID: c310cce1e620
Revises: c7b5b3014e6a
Create Date: 2026-09-02

Audit module "Mẻ sản xuất" (2026-09-02) phát hiện 2 chỗ thiếu backstop DB thật cho race
condition, chỉ có check-rồi-ghi kiểu Python thường ở tầng service:

1. batch_pack_lot.lot_no ("Số lô bia" — số GMP thật in trên bao bì) — mọi mã anh em khác
   (pack_lot_code/filter_lot_code/batch_code) đều có UniqueConstraint(year, code) thật, riêng
   lot_no thì không — 2 request tạo/sửa gần như đồng thời có thể lọt trùng.
2. ebr_snapshot(batch_id, snapshot_version) — khóa thủ công (lock_tank/lock_filter_lot/lock())
   và cascade khóa từ lô thành phẩm (_cascade_lock) đều chỉ check `if obj.locked: return` trước
   khi ghi, không có gì ngăn 2 giao dịch race cùng tạo snapshot cho 1 đối tượng.

Không cần recreate='auto' cho lot_no (thêm constraint MỚI trên bảng đã có, SQLite cho phép ALTER
TABLE ADD CONSTRAINT qua batch mode bình thường) — riêng ebr_snapshot cũng vậy, chỉ thêm ràng
buộc mới, không đổi/xóa constraint cũ nào.
"""
from alembic import op

revision = 'c310cce1e620'
down_revision = 'c7b5b3014e6a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_pack_lot', recreate='auto') as batch_op:
        batch_op.create_unique_constraint('uq_batch_pack_lot_year_lotno', ['pack_lot_year', 'lot_no'])
    with op.batch_alter_table('ebr_snapshot', recreate='auto') as batch_op:
        batch_op.create_unique_constraint('uq_ebr_snapshot_scope_version', ['batch_id', 'snapshot_version'])


def downgrade() -> None:
    with op.batch_alter_table('ebr_snapshot', recreate='auto') as batch_op:
        batch_op.drop_constraint('uq_ebr_snapshot_scope_version', type_='unique')
    with op.batch_alter_table('batch_pack_lot', recreate='auto') as batch_op:
        batch_op.drop_constraint('uq_batch_pack_lot_year_lotno', type_='unique')
