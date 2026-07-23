"""danh mục nhóm chỉ tiêu chất lượng NVL + gán cho nguyên liệu

Revision ID: c4d5e6f7a8b9
Revises: b1c2d3e4f5a6
Create Date: 2026-07-08

- qc_parameter: thêm method/note (phương pháp thử mặc định + ghi chú).
- qc_parameter_group / qc_parameter_group_item: nhóm chỉ tiêu (vd "Chỉ tiêu Malt Anh (bao)").
- material_qc_group: gán nhóm chỉ tiêu cho nguyên liệu — chỉ nguyên liệu có gán mới bị
  cổng nhập kho bắt buộc khai báo/duyệt chỉ tiêu trước khi coi là nhập kho nhà máy chính thức.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('qc_parameter', sa.Column('method', sa.Unicode(length=255), nullable=True))
    op.add_column('qc_parameter', sa.Column('note', sa.Unicode(length=255), nullable=True))

    op.create_table(
        'qc_parameter_group',
        sa.Column('group_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('group_id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('ix_qc_parameter_group_code', 'qc_parameter_group', ['code'])

    op.create_table(
        'qc_parameter_group_item',
        sa.Column('item_id', sa.Unicode(length=64), nullable=False),
        sa.Column('group_id', sa.Unicode(length=64), sa.ForeignKey('qc_parameter_group.group_id'), nullable=False),
        sa.Column('param_id', sa.Unicode(length=64), sa.ForeignKey('qc_parameter.param_id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mandatory', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('target_override', sa.Float(), nullable=True),
        sa.Column('usl_override', sa.Float(), nullable=True),
        sa.Column('lsl_override', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('item_id'),
    )
    op.create_index('ix_qc_parameter_group_item_group_id', 'qc_parameter_group_item', ['group_id'])
    op.create_index('ix_qc_parameter_group_item_param_id', 'qc_parameter_group_item', ['param_id'])

    op.create_table(
        'material_qc_group',
        sa.Column('link_id', sa.Unicode(length=64), nullable=False),
        sa.Column('material_id', sa.Unicode(length=64), sa.ForeignKey('material.material_id'), nullable=False),
        sa.Column('group_id', sa.Unicode(length=64), sa.ForeignKey('qc_parameter_group.group_id'), nullable=False),
        sa.Column('mandatory', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('link_id'),
    )
    op.create_index('ix_material_qc_group_material_id', 'material_qc_group', ['material_id'])
    op.create_index('ix_material_qc_group_group_id', 'material_qc_group', ['group_id'])


def downgrade() -> None:
    op.drop_table('material_qc_group')
    op.drop_table('qc_parameter_group_item')
    op.drop_table('qc_parameter_group')
    op.drop_column('qc_parameter', 'note')
    op.drop_column('qc_parameter', 'method')
