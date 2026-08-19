"""load_slip_line_product_code

Revision ID: 2d59542db9d4
Revises: c9d2e3f4a5b6
Create Date: 2026-08-17 20:53:19.314512

- load_slip_line.product_code (Unicode(64), nullable): mã SKU khai báo ở dòng "Mã sản phẩm"
  ngay dưới dòng tiêu đề trong file Excel "Lệnh đóng hàng" — giữ nguyên chuỗi gốc kể cả khi
  không khớp FinishedProduct nào (để phát hiện lỗi gõ mã).
- load_slip_line.finished_product_id (FK finished_product, nullable): chỉ set khi product_code
  khớp đúng 1 FinishedProduct.code. Cột "LON/Lốc ... KM" (khuyến mại rời phân rã từ 1 cột
  vỉ/thùng nguyên) khai BẰNG ĐÚNG mã của cột gốc — is_promo + uom khác đã đủ phân biệt.
"""
from alembic import op
import sqlalchemy as sa


revision = '2d59542db9d4'
down_revision = 'c9d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("load_slip_line", sa.Column("product_code", sa.Unicode(64), nullable=True))
    op.add_column("load_slip_line", sa.Column("finished_product_id", sa.Unicode(64), nullable=True))
    with op.batch_alter_table("load_slip_line") as batch_op:
        batch_op.create_foreign_key(
            "fk_load_slip_line_finished_product", "finished_product",
            ["finished_product_id"], ["finished_product_id"])
    op.create_index("ix_load_slip_line_finished_product_id", "load_slip_line", ["finished_product_id"])


def downgrade() -> None:
    op.drop_index("ix_load_slip_line_finished_product_id", table_name="load_slip_line")
    with op.batch_alter_table("load_slip_line") as batch_op:
        batch_op.drop_constraint("fk_load_slip_line_finished_product", type_="foreignkey")
    op.drop_column("load_slip_line", "finished_product_id")
    op.drop_column("load_slip_line", "product_code")
