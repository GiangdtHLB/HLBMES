"""Nhóm vật tư thay thế (MaterialAltGroup) + brew_order_material_line.material_group_code

Revision ID: 585b9bb8e072
Revises: a3b4c5d6e7f9
Create Date: 2026-08-01

- material_alt_group: nhóm các mã vật tư CÙNG BẢN CHẤT, khác quy cách đóng gói/nhà cung cấp
  (VD "Malt Úc" gồm Malt Úc rời + Malt Úc bao). Công thức có thể khai 1 dòng NVL bằng NHÓM
  này thay vì 1 material_code cụ thể — thủ kho tự chọn mã cụ thể lúc xuất kho thật (xem
  services/brew_order.py::_resolve_group_members). KHÁC với material_group hiện có (đó là
  phân loại rộng malt/gạo/hoa bia dùng cho QC/bao bì, không phải tập vật tư thay thế nhau).
- brew_order_material_line.material_group_code: đánh dấu 1 dòng Định mức trong Lệnh nấu được
  nạp từ 1 Nhóm vật tư thay thế (thay vì material_id cụ thể) — dùng để gợi ý đúng mọi mã
  thành viên của nhóm lúc ghi NVL thực tế cho mẻ (openBrewMaterialsModal).
"""
from alembic import op
import sqlalchemy as sa

revision = '585b9bb8e072'
down_revision = 'a3b4c5d6e7f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'material_alt_group',
        sa.Column('group_id', sa.Unicode(64), primary_key=True),
        sa.Column('code', sa.Unicode(64), nullable=False),
        sa.Column('name', sa.Unicode(255), nullable=False),
        sa.Column('member_material_ids', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_material_alt_group_code', 'material_alt_group', ['code'], unique=True)

    with op.batch_alter_table('brew_order_material_line', recreate='auto') as batch_op:
        batch_op.add_column(sa.Column('material_group_code', sa.Unicode(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('brew_order_material_line', recreate='auto') as batch_op:
        batch_op.drop_column('material_group_code')

    op.drop_index('ix_material_alt_group_code', table_name='material_alt_group')
    op.drop_table('material_alt_group')
