"""batch_pack_lot_stocked

Revision ID: 4e8b6c1d9a2f
Revises: 9c3d7f1a2b4e
Create Date: 2026-08-31 00:00:00.000000

Thêm stocked/stocked_by/stocked_at vào batch_pack_lot — mirror BottleRecord.stocked (module
Nấu-Lọc-Chiết cũ). Đánh dấu lô thành phẩm đã được duyệt nhập kho thành phẩm (WMS) — tách khỏi
`approved` (Duyệt KCS), xem services/batch_pipeline.py::release_pack_lot_to_wms.
"""
from alembic import op
import sqlalchemy as sa


revision = '4e8b6c1d9a2f'
down_revision = '9c3d7f1a2b4e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_pack_lot', sa.Column('stocked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('batch_pack_lot', sa.Column('stocked_by', sa.Unicode(length=255), nullable=True))
    op.add_column('batch_pack_lot', sa.Column('stocked_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('batch_pack_lot', 'stocked_at')
    op.drop_column('batch_pack_lot', 'stocked_by')
    op.drop_column('batch_pack_lot', 'stocked')
