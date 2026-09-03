"""recipe_version_catalog_items

Revision ID: bdffb11551d9
Revises: 021bf4a8794b
Create Date: 2026-08-30 00:00:00.000000

Recipe chọn chỉ tiêu/tham số từ danh mục thay vì gõ tay JSON — thêm 2 bảng liên kết
`recipe_version_qc_item` (RecipeVersion ↔ QCParameter, mirror qc_parameter_group_item) và
`recipe_version_param_item` (RecipeVersion ↔ ProcessParameter, mirror process_parameter_group_item).
Không đổi 2 cột JSON cũ (`recipe_version.parameters`/`.quality_checks`) — vẫn được tự tính/ghi
đè từ 2 bảng mới này (xem services/recipes.py::create_version/update_draft).
"""
from alembic import op
import sqlalchemy as sa


revision = 'bdffb11551d9'
down_revision = '021bf4a8794b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'recipe_version_qc_item',
        sa.Column('link_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('version_id', sa.Unicode(length=64), nullable=False),
        sa.Column('param_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('mandatory', sa.Boolean(), nullable=False),
        sa.Column('target_override', sa.Float(), nullable=True),
        sa.Column('usl_override', sa.Float(), nullable=True),
        sa.Column('lsl_override', sa.Float(), nullable=True),
    )
    op.create_index('ix_recipe_version_qc_item_version_id', 'recipe_version_qc_item', ['version_id'])
    op.create_index('ix_recipe_version_qc_item_param_id', 'recipe_version_qc_item', ['param_id'])

    op.create_table(
        'recipe_version_param_item',
        sa.Column('link_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('version_id', sa.Unicode(length=64), nullable=False),
        sa.Column('param_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('mandatory', sa.Boolean(), nullable=False),
        sa.Column('phase_override', sa.Unicode(length=255), nullable=True),
        sa.Column('target_override', sa.Float(), nullable=True),
        sa.Column('usl_override', sa.Float(), nullable=True),
        sa.Column('lsl_override', sa.Float(), nullable=True),
    )
    op.create_index('ix_recipe_version_param_item_version_id', 'recipe_version_param_item', ['version_id'])
    op.create_index('ix_recipe_version_param_item_param_id', 'recipe_version_param_item', ['param_id'])


def downgrade() -> None:
    op.drop_table('recipe_version_param_item')
    op.drop_table('recipe_version_qc_item')
