"""Pallet: thêm cột source (manual|production) để phân biệt pallet "Đóng pallet" thủ công
(thủ kho, quyền warehouse.receive) với pallet tạo tự động qua duyệt chiết
(release_pack_lot_to_wms, quyền production.release_to_wms) — theo audit rủi ro 2026-09-15:
pallet thủ công không đi qua duyệt KCS/Giám đốc SX và không link genealogy về lô chiết gốc,
nên cần đánh dấu rõ để phân biệt khi xem danh sách/kiểm toán, KHÔNG đổi quyền/không chặn ai
(giữ nguyên tính năng thủ công hiện có theo quyết định người dùng).

Revision ID: d921c6f199cd
Revises: c749b25aba5c
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'd921c6f199cd'
down_revision = 'c749b25aba5c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('pallet', sa.Column('source', sa.Unicode(length=32), nullable=False,
                                       server_default='manual'))


def downgrade() -> None:
    op.drop_column('pallet', 'source')
