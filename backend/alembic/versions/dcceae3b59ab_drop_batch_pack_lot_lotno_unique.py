"""drop_batch_pack_lot_lotno_unique

Gỡ UniqueConstraint (pack_lot_year, lot_no) trên batch_pack_lot — "Số lô bia" không còn bị chặn
cứng khi trùng nữa, chuyển sang cảnh báo + xác nhận lại ở tầng service
(split_filter_lot_to_pack_lot::confirm_duplicate_lot_no) — yêu cầu người dùng 2026-10-01: "cho
phép nhập 2 lô giống nhau và hỏi bạn có muốn nhập 2 lô giống nhau không". Ràng buộc này được
thêm ở migration trước (gắn với audit "Mẻ sản xuất" 2026-09-02) — không cần di trú dữ liệu khi
gỡ (gỡ ràng buộc luôn tương thích ngược, dữ liệu hiện có không đổi).

Revision ID: dcceae3b59ab
Revises: 82828129a3d1
Create Date: 2026-10-01 00:00:00.000000
"""
from alembic import op


revision = 'dcceae3b59ab'
down_revision = '82828129a3d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('batch_pack_lot') as batch_op:
        batch_op.drop_constraint('uq_batch_pack_lot_year_lotno', type_='unique')


def downgrade() -> None:
    with op.batch_alter_table('batch_pack_lot') as batch_op:
        batch_op.create_unique_constraint('uq_batch_pack_lot_year_lotno', ['pack_lot_year', 'lot_no'])
