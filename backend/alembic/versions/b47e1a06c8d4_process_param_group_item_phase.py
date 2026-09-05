"""process_param_group_item_phase

Revision ID: b47e1a06c8d4
Revises: 9c3d7a1f5e2b
Create Date: 2026-09-05 00:00:00.000000

Thêm cột phase_override vào process_parameter_group_item — ghi đè công đoạn (ProcessPhase.code)
cho 1 tham số trong 1 nhóm cụ thể, mirror RecipeVersionParamItem.phase_override, để copy nguyên
nhóm vào version công thức mang sẵn đúng bước — xem models/quality_ext.py::
ProcessParameterGroupItem, services/param_catalog.py.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b47e1a06c8d4'
down_revision = '9c3d7a1f5e2b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('process_parameter_group_item',
                   sa.Column('phase_override', sa.Unicode(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('process_parameter_group_item', 'phase_override')
