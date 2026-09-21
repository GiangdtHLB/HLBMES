"""Quy cách đóng gói pallet (packing_spec) — danh mục theo SKU

Revision ID: d3c4b5a69788
Revises: 95ba9f0257a3
Create Date: 2026-09-20

1 bảng mới, không đổi bảng nào có sẵn — danh mục "Quy cách đóng gói pallet" theo TỪNG SKU
(finished_product_id): units_per_pallet (số vỉ/keg mỗi pallet) + layers (số hàng xếp cao, chỉ
tham khảo). Dùng ở bước "Duyệt nhập kho thành phẩm" (services/batch_pipeline.py::
release_pack_lot_to_wms) để tách đúng số pallet thật theo quy cách đã dùng, thay vì gộp hết
SL đã chiết vào 1 pallet duy nhất (yêu cầu người dùng 2026-09-20)."""
from alembic import op
import sqlalchemy as sa

revision = 'd3c4b5a69788'
down_revision = '95ba9f0257a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'packing_spec',
        sa.Column('spec_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=True),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=False),
        sa.Column('units_per_pallet', sa.Integer(), nullable=False),
        sa.Column('layers', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.PrimaryKeyConstraint('spec_id'),
        sa.UniqueConstraint('finished_product_id', 'code', name='uq_packing_spec_product_code'),
    )
    op.create_index('ix_packing_spec_code', 'packing_spec', ['code'])
    op.create_index('ix_packing_spec_finished_product_id', 'packing_spec', ['finished_product_id'])


def downgrade() -> None:
    op.drop_index('ix_packing_spec_finished_product_id', table_name='packing_spec')
    op.drop_index('ix_packing_spec_code', table_name='packing_spec')
    op.drop_table('packing_spec')
