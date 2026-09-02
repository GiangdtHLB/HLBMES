"""process_parameter_catalog

Revision ID: 021bf4a8794b
Revises: 54e88b2beb92
Create Date: 2026-08-30 00:00:00.000000

Danh mục "Tham số quy trình" (setpoint công nghệ, VD nhiệt độ đường hóa/lên men) — mirror
đúng cấu trúc qc_parameter/qc_parameter_group/qc_parameter_group_item (không FK constraint
thật, mirror quy ước các bảng danh mục "mềm" trong dự án) — xem models/quality_ext.py::
ProcessParameter/ProcessParameterGroup/ProcessParameterGroupItem, services/param_catalog.py.
"""
from alembic import op
import sqlalchemy as sa


revision = '021bf4a8794b'
down_revision = '54e88b2beb92'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'process_parameter',
        sa.Column('param_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('unit', sa.Unicode(length=255), nullable=True),
        sa.Column('target', sa.Float(), nullable=True),
        sa.Column('usl', sa.Float(), nullable=True),
        sa.Column('lsl', sa.Float(), nullable=True),
        sa.Column('phase', sa.Unicode(length=255), nullable=True),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
    )
    op.create_index('ix_process_parameter_code', 'process_parameter', ['code'], unique=True)

    op.create_table(
        'process_parameter_group',
        sa.Column('group_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
    )
    op.create_index('ix_process_parameter_group_code', 'process_parameter_group', ['code'], unique=True)

    op.create_table(
        'process_parameter_group_item',
        sa.Column('item_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('group_id', sa.Unicode(length=64), nullable=False),
        sa.Column('param_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('mandatory', sa.Boolean(), nullable=False),
        sa.Column('target_override', sa.Float(), nullable=True),
        sa.Column('usl_override', sa.Float(), nullable=True),
        sa.Column('lsl_override', sa.Float(), nullable=True),
    )
    op.create_index('ix_process_parameter_group_item_group_id', 'process_parameter_group_item', ['group_id'])
    op.create_index('ix_process_parameter_group_item_param_id', 'process_parameter_group_item', ['param_id'])


def downgrade() -> None:
    op.drop_table('process_parameter_group_item')
    op.drop_index('ix_process_parameter_group_code', table_name='process_parameter_group')
    op.drop_table('process_parameter_group')
    op.drop_index('ix_process_parameter_code', table_name='process_parameter')
    op.drop_table('process_parameter')
