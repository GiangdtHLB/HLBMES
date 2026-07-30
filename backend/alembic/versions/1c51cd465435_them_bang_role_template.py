"""them bang role_template

Revision ID: 1c51cd465435
Revises: ad9ecba3cfc2
Create Date: 2026-07-27 22:51:18.037930

Mẫu chức danh (RoleTemplate) — admin tự khai báo tên chức danh + vai trò hệ thống + menu/
quyền/phạm vi mặc định để chọn nhanh khi tạo tài khoản mới. Không thay thế Role enum (vẫn
dùng để require_role() chặn quyền ở backend) — chỉ là lớp đóng gói/đặt tên bên trên.
"""
from alembic import op
import sqlalchemy as sa


revision = '1c51cd465435'
down_revision = 'ad9ecba3cfc2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'role_template',
        sa.Column('role_template_id', sa.Unicode(64), primary_key=True),
        sa.Column('name', sa.Unicode(255), nullable=False),
        sa.Column('role', sa.Unicode(255), nullable=False),
        sa.Column('allowed_views', sa.UnicodeText(), nullable=False),
        sa.Column('permissions', sa.UnicodeText(), nullable=False),
        sa.Column('scope_lines', sa.Unicode(255), nullable=False),
        sa.Column('scope_areas', sa.Unicode(255), nullable=False),
        sa.Column('scope_qc', sa.Unicode(255), nullable=False),
        sa.Column('scope_warehouse', sa.Unicode(255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('role_template')
