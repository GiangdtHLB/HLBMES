"""Nhóm vật tư thay thế: bắt buộc chọn đơn vị của nhóm (đơn vị chính hoặc phụ chung của mọi
thành viên)

Revision ID: e17b49fe0d06
Revises: b624e7bc6d4d
Create Date: 2026-08-05

- material_alt_group.unit (nullable ở DB để migrate dữ liệu cũ, nhưng router luôn bắt buộc
  cho request mới — xem services/master_data.py::validate_alt_group_unit). Backfill nhóm cũ
  bằng uom của thành viên đầu tiên (best-effort — dữ liệu cũ trước tính năng này không có
  đơn vị phụ nên hầu như luôn đồng nhất giữa các thành viên).
"""
from alembic import op
import sqlalchemy as sa
import json

revision = 'e17b49fe0d06'
down_revision = 'b624e7bc6d4d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('material_alt_group', sa.Column('unit', sa.Unicode(length=64), nullable=True))
    bind = op.get_bind()
    groups = bind.execute(sa.text("SELECT group_id, member_material_ids FROM material_alt_group")).fetchall()
    for group_id, member_ids_raw in groups:
        member_ids = member_ids_raw if isinstance(member_ids_raw, list) else json.loads(member_ids_raw or "[]")
        if not member_ids:
            continue
        row = bind.execute(sa.text("SELECT uom FROM material WHERE material_id = :mid"),
                            {"mid": member_ids[0]}).fetchone()
        if row and row[0]:
            bind.execute(sa.text("UPDATE material_alt_group SET unit = :unit WHERE group_id = :gid"),
                         {"unit": row[0], "gid": group_id})


def downgrade() -> None:
    op.drop_column('material_alt_group', 'unit')
