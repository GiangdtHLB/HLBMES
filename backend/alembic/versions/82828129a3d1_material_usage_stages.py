"""material_usage_stages

Thêm cột `usage_stages` (JSON, danh sách mã công đoạn) trên Material — "Nơi dùng" của vật tư,
cho phép nhiều giá trị (nau/len_men/loc/thanh_pham/cip) — yêu cầu người dùng 2026-10-01: "nguyên
vật liệu bổ sung thêm nơi dùng, có thể nhiều vị trí". Mặc định rỗng ([]) cho mọi dòng cũ (chưa
khai báo) — không bắt buộc, chỉ dùng gợi ý/lọc nhanh ở Danh mục, không ảnh hưởng xuất kho.

Revision ID: 82828129a3d1
Revises: 56a90b371cf6
Create Date: 2026-10-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '82828129a3d1'
down_revision = '56a90b371cf6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('material') as batch_op:
        batch_op.add_column(sa.Column('usage_stages', sa.JSON(), nullable=True))
    op.execute("UPDATE material SET usage_stages = '[]' WHERE usage_stages IS NULL")
    with op.batch_alter_table('material') as batch_op:
        # existing_type BẮT BUỘC khi đổi NULL/NOT NULL: MSSQL cần kiểu để sinh
        # "ALTER TABLE ... ALTER COLUMN <col> <type> NOT NULL" (alembic báo lỗi cứng nếu thiếu;
        # SQLite recreate bảng nên không cần, vì vậy bỏ sót không lộ khi test trên SQLite).
        batch_op.alter_column('usage_stages', existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('material') as batch_op:
        batch_op.drop_column('usage_stages')
