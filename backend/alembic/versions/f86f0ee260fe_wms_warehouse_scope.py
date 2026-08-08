"""Phân quyền thao tác kho thành phẩm (WMS) theo kho được gán — khác scope_warehouse (chỉ
cong_ty/phan_xuong cho kho NVL).

Revision ID: f86f0ee260fe
Revises: b8c9d0e1f2a4
Create Date: 2026-08-08

- app_user.wms_warehouse_scope / role_template.wms_warehouse_scope (Unicode(255), default "*"):
  csv mã Kho thành phẩm (WmsWarehouse.code, vd "KH01,KH02") hoặc "*" — chặn Xuất kho/Điều
  chuyển/Nhập kho/Cất vào vị trí/Nhập từ nhà máy khác ngoài kho được phân (xem
  security.py::_SCOPE_DIMENSION_ATTR["wms_warehouse"], services/wms.py::_assert_wh_scope).
"""
from alembic import op
import sqlalchemy as sa

revision = "f86f0ee260fe"
down_revision = "b8c9d0e1f2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("wms_warehouse_scope", sa.Unicode(length=255),
                                        nullable=False, server_default="*"))
    op.add_column("role_template", sa.Column("wms_warehouse_scope", sa.Unicode(length=255),
                                             nullable=False, server_default="*"))


def downgrade() -> None:
    op.drop_column("role_template", "wms_warehouse_scope")
    op.drop_column("app_user", "wms_warehouse_scope")
