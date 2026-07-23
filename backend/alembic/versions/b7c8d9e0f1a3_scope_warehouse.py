"""Phân quyền theo địa điểm kho: app_user.scope_warehouse

Revision ID: b7c8d9e0f1a3
Revises: c3d4e5f6a7b8
Create Date: 2026-07-23

- app_user.scope_warehouse (csv|'*'): chiều data-scoping thứ 4 (bên cạnh
  scope_lines/scope_areas/scope_qc) — giá trị "cong_ty" | "phan_xuong" | "*",
  dùng để chặn thao tác kho NVL ngoài phạm vi địa điểm được phân (xem
  services/warehouse.py::_assert_location_scope/_assert_transfer_scope).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a3'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('app_user', sa.Column('scope_warehouse', sa.Unicode(length=255),
                                        nullable=False, server_default="*"))


def downgrade() -> None:
    op.drop_column('app_user', 'scope_warehouse')
