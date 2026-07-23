"""Danh mục Nhóm vật tư (thay danh sách cứng trong frontend)

Revision ID: e8f9a1b2c4d6
Revises: d7e8f9a1b2c4
Create Date: 2026-07-21

- material_group: bảng mới — code/name/active, quản lý được (thêm/sửa/xóa) thay vì danh
  sách cứng "malt/hop/yeast/adjunct/packaging/chemical/other" từng nằm cứng trong form Tạo
  vật tư (trong khi form Sửa lại cho nhập tự do, nên dữ liệu có thể lệch khỏi danh sách đó).
- Seed: 7 nhóm cứng cũ + mọi giá trị material.category đang thực sự được dùng (để không có
  vật tư nào bị "mồ côi" nhóm sau khi chuyển sang chọn từ danh mục).
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = 'e8f9a1b2c4d6'
down_revision = 'd7e8f9a1b2c4'
branch_labels = None
depends_on = None

_DEFAULT_GROUPS = [
    ("malt", "Malt"), ("hop", "Hoa bia"), ("yeast", "Men"), ("adjunct", "Nguyên liệu thay thế"),
    ("packaging", "Bao bì"), ("chemical", "Hóa chất"), ("other", "Khác"),
]


def upgrade() -> None:
    op.create_table(
        'material_group',
        sa.Column('group_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
    )
    op.create_index('ix_material_group_code', 'material_group', ['code'], unique=True)

    conn = op.get_bind()

    codes_seen = set()
    rows = []
    for code, name in _DEFAULT_GROUPS:
        codes_seen.add(code)
        rows.append({"group_id": str(uuid.uuid4()), "code": code, "name": name, "active": True})

    existing = conn.execute(sa.text(
        "SELECT DISTINCT category FROM material WHERE category IS NOT NULL AND category <> ''"
    )).fetchall()
    for (cat,) in existing:
        if cat not in codes_seen:
            codes_seen.add(cat)
            rows.append({"group_id": str(uuid.uuid4()), "code": cat, "name": cat, "active": True})

    if rows:
        table = sa.table('material_group', sa.column('group_id'), sa.column('code'),
                         sa.column('name'), sa.column('active'))
        op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_index('ix_material_group_code', table_name='material_group')
    op.drop_table('material_group')
