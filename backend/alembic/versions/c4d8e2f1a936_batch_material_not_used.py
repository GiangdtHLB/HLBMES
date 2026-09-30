"""batch_material_not_used — xác nhận dòng BOM "Chưa dùng" là chủ ý "Không sử dụng"
(2026-09-30)

Revision ID: c4d8e2f1a936
Revises: b3f8c1d97a02
Create Date: 2026-09-30

Bảng mới, không có dữ liệu cũ để backfill (tính năng chưa từng tồn tại trước migration này —
mọi dòng "chua_dung" trước đây đều thật sự chỉ là "chưa biết", coi như đúng thực tế)."""
from alembic import op
import sqlalchemy as sa

revision = 'c4d8e2f1a936'
down_revision = 'b3f8c1d97a02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'batch_material_not_used',
        sa.Column('id', sa.Unicode(length=64), primary_key=True),
        sa.Column('batch_id', sa.Unicode(length=64), sa.ForeignKey('batch_execution.batch_id'), nullable=False),
        sa.Column('material_code', sa.Unicode(length=64), nullable=False),
        sa.Column('confirmed_by', sa.Unicode(length=255), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('batch_id', 'material_code', name='uq_batch_material_not_used'),
    )
    op.create_index('ix_batch_material_not_used_batch_id', 'batch_material_not_used', ['batch_id'])
    op.create_index('ix_batch_material_not_used_material_code', 'batch_material_not_used', ['material_code'])


def downgrade() -> None:
    op.drop_index('ix_batch_material_not_used_material_code', table_name='batch_material_not_used')
    op.drop_index('ix_batch_material_not_used_batch_id', table_name='batch_material_not_used')
    op.drop_table('batch_material_not_used')
