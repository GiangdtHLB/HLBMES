"""filter_order/filter_record.finished_product_id — chỉ tiêu Lọc theo SKU đích

Revision ID: b1c2d3e4f5a7
Revises: a1b2c3d4e5f7
Create Date: 2026-07-19

- filter_order.finished_product_id: khai báo tuỳ chọn 1 lần khi lập Lệnh lọc — cùng 1
  Loại bia vẫn có thể cần chỉ tiêu Lọc khác nhau theo hình thức đóng gói đích (VD Legend
  chai lọc khác Legend tươi).
- filter_record.finished_product_id: kế thừa từ filter_order khi tạo mẻ lọc (mirror cách
  beer_type_id được kế thừa), dùng để tra chỉ tiêu Lọc (xem qc_catalog.SKU_SCOPED_STAGES —
  giờ gồm cả "loc", không chỉ "thanh_pham").
Không backfill dữ liệu — để trống = áp dụng chung cho mọi sản phẩm như trước.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a7'
down_revision = '55dcafa5a7f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('filter_order', sa.Column('finished_product_id', sa.Unicode(64), nullable=True))
    op.create_index('ix_filter_order_finished_product_id', 'filter_order', ['finished_product_id'])

    op.add_column('filter_record', sa.Column('finished_product_id', sa.Unicode(64), nullable=True))
    op.create_index('ix_filter_record_finished_product_id', 'filter_record', ['finished_product_id'])


def downgrade() -> None:
    op.drop_index('ix_filter_record_finished_product_id', table_name='filter_record')
    op.drop_column('filter_record', 'finished_product_id')

    op.drop_index('ix_filter_order_finished_product_id', table_name='filter_order')
    op.drop_column('filter_order', 'finished_product_id')
