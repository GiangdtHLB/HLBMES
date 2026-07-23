"""Sản phẩm thành phẩm (SKU đóng gói) — khác Product (dịch bia)

Revision ID: a9b0c1d2e3f4
Revises: f2a3b4c5d6e7
Create Date: 2026-07-09

- finished_product: danh mục SKU đóng gói (chai/lon/keg...), tuỳ chọn tham chiếu tới
  Product (dịch bia gốc) — tài liệu §5.2.
- bottle_record: thêm finished_product_id — chọn khi chiết, cùng với tank BBT nguồn.
- stage_qc_group: thêm finished_product_id — cho phép gán nhóm chỉ tiêu thành phẩm
  (stage=thanh_pham) theo từng SKU cụ thể, thay vì chỉ theo dịch bia.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a9b0c1d2e3f4'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'finished_product',
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False),
        sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id'), nullable=True),
        sa.Column('description', sa.UnicodeText(), nullable=True),
        sa.PrimaryKeyConstraint('finished_product_id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('ix_finished_product_code', 'finished_product', ['code'])
    op.create_index('ix_finished_product_product_id', 'finished_product', ['product_id'])

    with op.batch_alter_table('bottle_record') as batch_op:
        batch_op.add_column(sa.Column('finished_product_id', sa.Unicode(length=64),
                      sa.ForeignKey('finished_product.finished_product_id', name='fk_bottle_record_finished_product_id_finished_product'), nullable=True))
        batch_op.create_index('ix_bottle_record_finished_product_id', ['finished_product_id'])

    with op.batch_alter_table('stage_qc_group') as batch_op:
        batch_op.add_column(sa.Column('finished_product_id', sa.Unicode(length=64),
                      sa.ForeignKey('finished_product.finished_product_id', name='fk_stage_qc_group_finished_product_id_finished_product'), nullable=True))
        batch_op.create_index('ix_stage_qc_group_finished_product_id', ['finished_product_id'])


def downgrade() -> None:
    with op.batch_alter_table('stage_qc_group') as batch_op:
        batch_op.drop_index('ix_stage_qc_group_finished_product_id')
        batch_op.drop_column('finished_product_id')
    with op.batch_alter_table('bottle_record') as batch_op:
        batch_op.drop_index('ix_bottle_record_finished_product_id')
        batch_op.drop_column('finished_product_id')
    op.drop_table('finished_product')
