"""process_phase_catalog

Revision ID: 9c3d7a1f5e2b
Revises: a1e7f3c9b2d4
Create Date: 2026-09-04 00:00:00.000000

Danh mục "Công đoạn" (VD "Đường hóa", "Đun sôi") — trước đây ProcessParameter.phase và
RecipeVersionParamItem.phase_override là gõ tay tự do, nay khai báo 1 lần ở đây rồi chọn
(không FK constraint thật, mirror quy ước các bảng danh mục "mềm" trong dự án) — xem
models/quality_ext.py::ProcessPhase, services/param_catalog.py.
"""
from alembic import op
import sqlalchemy as sa


revision = '9c3d7a1f5e2b'
down_revision = 'a1e7f3c9b2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'process_phase',
        sa.Column('phase_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
    )
    op.create_index('ix_process_phase_code', 'process_phase', ['code'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_process_phase_code', table_name='process_phase')
    op.drop_table('process_phase')
