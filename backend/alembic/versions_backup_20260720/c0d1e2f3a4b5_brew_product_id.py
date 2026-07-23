"""loại bia (product_id) trên mẻ nấu/lô LM/lô lọc/mã chiết

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-07-09

- brew_record/ferment_record/filter_record/bottle_record: thêm product_id (FK product)
  để chọn nhóm chỉ tiêu chất lượng đúng theo loại bia (StageQcGroup.product_id).
"""
from alembic import op
import sqlalchemy as sa

revision = 'c0d1e2f3a4b5'
down_revision = 'b9c0d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_record', sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id'), nullable=True))
    op.create_index('ix_brew_record_product_id', 'brew_record', ['product_id'])

    op.add_column('ferment_record', sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id'), nullable=True))
    op.create_index('ix_ferment_record_product_id', 'ferment_record', ['product_id'])

    op.add_column('filter_record', sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id'), nullable=True))
    op.create_index('ix_filter_record_product_id', 'filter_record', ['product_id'])

    op.add_column('bottle_record', sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id'), nullable=True))
    op.create_index('ix_bottle_record_product_id', 'bottle_record', ['product_id'])


def downgrade() -> None:
    op.drop_column('bottle_record', 'product_id')
    op.drop_column('filter_record', 'product_id')
    op.drop_column('ferment_record', 'product_id')
    op.drop_column('brew_record', 'product_id')
