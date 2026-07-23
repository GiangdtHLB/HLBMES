"""loại bia (BeerType) — tách khỏi Dịch bia, dùng cho chỉ tiêu Lọc/Chiết

Revision ID: c8d9e0f1a2b3
Revises: d7e8f9a1b2c3
Create Date: 2026-07-19

- beer_type: bảng mới (code/name/note) — thương hiệu bia (VD Sapphire), 1 Dịch bia
  (Product, có thể khác độ oP) thuộc về 1 Loại bia.
- product.beer_type_id: gán Dịch bia vào Loại bia.
- filter_order.beer_type_id / filter_record.beer_type_id / bottle_record.beer_type_id:
  suy ra lúc lập lệnh lọc, kế thừa xuống mẻ lọc/mẻ chiết — dùng để tra chỉ tiêu QC thay
  vì product_id (xem stage_qc_group.beer_type_id).
- stage_qc_group.beer_type_id: cột song song với product_id, dùng riêng cho stage
  loc|thanh_pham (product_id tiếp tục dùng cho nau|len_men_chinh|len_men_phu).
Không backfill dữ liệu — admin tự gán Loại bia cho Dịch bia + re-link StageQcGroup sau
khi deploy.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8d9e0f1a2b3'
down_revision = 'd7e8f9a1b2c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'beer_type',
        sa.Column('beer_type_id', sa.Unicode(64), primary_key=True),
        sa.Column('code', sa.Unicode(64), nullable=False),
        sa.Column('name', sa.Unicode(255), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
    )
    op.create_index('ix_beer_type_code', 'beer_type', ['code'], unique=True)

    op.add_column('product', sa.Column('beer_type_id', sa.Unicode(64), nullable=True))
    op.create_index('ix_product_beer_type_id', 'product', ['beer_type_id'])

    op.add_column('filter_order', sa.Column('beer_type_id', sa.Unicode(64), nullable=True))
    op.create_index('ix_filter_order_beer_type_id', 'filter_order', ['beer_type_id'])

    op.add_column('filter_record', sa.Column('beer_type_id', sa.Unicode(64), nullable=True))
    op.create_index('ix_filter_record_beer_type_id', 'filter_record', ['beer_type_id'])

    op.add_column('bottle_record', sa.Column('beer_type_id', sa.Unicode(64), nullable=True))
    op.create_index('ix_bottle_record_beer_type_id', 'bottle_record', ['beer_type_id'])

    op.add_column('stage_qc_group', sa.Column('beer_type_id', sa.Unicode(64), nullable=True))
    op.create_index('ix_stage_qc_group_beer_type_id', 'stage_qc_group', ['beer_type_id'])


def downgrade() -> None:
    op.drop_index('ix_stage_qc_group_beer_type_id', table_name='stage_qc_group')
    op.drop_column('stage_qc_group', 'beer_type_id')

    op.drop_index('ix_bottle_record_beer_type_id', table_name='bottle_record')
    op.drop_column('bottle_record', 'beer_type_id')

    op.drop_index('ix_filter_record_beer_type_id', table_name='filter_record')
    op.drop_column('filter_record', 'beer_type_id')

    op.drop_index('ix_filter_order_beer_type_id', table_name='filter_order')
    op.drop_column('filter_order', 'beer_type_id')

    op.drop_index('ix_product_beer_type_id', table_name='product')
    op.drop_column('product', 'beer_type_id')

    op.drop_index('ix_beer_type_code', table_name='beer_type')
    op.drop_table('beer_type')
