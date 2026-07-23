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
    with op.batch_alter_table('brew_record') as batch:
        batch.add_column(sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id', name='fk_brew_record_product_id_product'), nullable=True))
        batch.create_index('ix_brew_record_product_id', ['product_id'])

    with op.batch_alter_table('ferment_record') as batch:
        batch.add_column(sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id', name='fk_ferment_record_product_id_product'), nullable=True))
        batch.create_index('ix_ferment_record_product_id', ['product_id'])

    with op.batch_alter_table('filter_record') as batch:
        batch.add_column(sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id', name='fk_filter_record_product_id_product'), nullable=True))
        batch.create_index('ix_filter_record_product_id', ['product_id'])

    with op.batch_alter_table('bottle_record') as batch:
        batch.add_column(sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id', name='fk_bottle_record_product_id_product'), nullable=True))
        batch.create_index('ix_bottle_record_product_id', ['product_id'])


def downgrade() -> None:
    with op.batch_alter_table('bottle_record') as batch:
        batch.drop_column('product_id')
    with op.batch_alter_table('filter_record') as batch:
        batch.drop_column('product_id')
    with op.batch_alter_table('ferment_record') as batch:
        batch.drop_column('product_id')
    with op.batch_alter_table('brew_record') as batch:
        batch.drop_column('product_id')
