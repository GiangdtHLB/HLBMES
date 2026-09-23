"""batch_pack_lot_finished

Revision ID: a7d4e29f6c51
Revises: f8250db1e3e2
Create Date: 2026-09-23 00:00:00.000000

Thêm finished/finished_by/finished_at vào batch_pack_lot — mốc "Hoàn thành chiết" xác nhận
riêng của vận hành (mirror BatchFilterLot.status "dang_loc"->"hoan_thanh" qua finish_filtering,
xem 18153f3ab494_batch_filter_lot_qc_approved.py). BatchPackLot.status trước đây CHỈ suy tự động
từ ca1/2/3 + độ rỗng tank BBT nguồn (dang_chiet/chiet_1_phan/chiet_het, xem _pack_lot_status),
KHÔNG có mốc xác nhận thủ công nào — yêu cầu người dùng 2026-09-23: "chiết thiếu ô trạng thái,
thiếu nút hoàn thành chiết". Cờ RIÊNG, KHÁC quality_status/approved (Duyệt KCS)/stocked (nhập
kho) — 2 luồng đó đã độc lập nhau, mốc "hoàn thành chiết" độc lập với cả 2.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7d4e29f6c51'
down_revision = 'f8250db1e3e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_pack_lot', sa.Column('finished', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('batch_pack_lot', sa.Column('finished_by', sa.Unicode(length=255), nullable=True))
    op.add_column('batch_pack_lot', sa.Column('finished_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('batch_pack_lot', 'finished_at')
    op.drop_column('batch_pack_lot', 'finished_by')
    op.drop_column('batch_pack_lot', 'finished')
