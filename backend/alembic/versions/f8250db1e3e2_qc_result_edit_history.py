"""quality_result.updated_by/updated_at + quality_result_history — sửa chỉ tiêu QC có ghi
lại lịch sử (2026-09-21)

Revision ID: f8250db1e3e2
Revises: dfa73fa4a3db
Create Date: 2026-09-21

Cột mới, nullable — recorded_by/recorded_at giữ đúng nghĩa "lúc tạo lần đầu" từ giờ, không bị
ghi đè mỗi lần sửa nữa (dữ liệu cũ không cần backfill: coi như "chưa từng sửa" là đúng thực
tế, vì trước migration này không có cách nào sửa được). Bảng history mới để chụp lại giá trị
trước mỗi lần sửa — không có dữ liệu cũ để backfill (lịch sử sửa chỉ bắt đầu tính từ đây)."""
from alembic import op
import sqlalchemy as sa

revision = 'f8250db1e3e2'
down_revision = 'dfa73fa4a3db'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('quality_result') as batch_op:
        batch_op.add_column(sa.Column('updated_by', sa.Unicode(length=255), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'quality_result_history',
        sa.Column('history_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('result_id', sa.Unicode(length=64), nullable=False),
        sa.Column('value', sa.Float(), nullable=True),
        sa.Column('value_text', sa.Unicode(length=1000), nullable=True),
        sa.Column('unit', sa.Unicode(length=255), nullable=True),
        sa.Column('lower_limit', sa.Float(), nullable=True),
        sa.Column('upper_limit', sa.Float(), nullable=True),
        sa.Column('status', sa.Unicode(length=255), nullable=False),
        sa.Column('sampled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('saved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('saved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('changed_by', sa.Unicode(length=255), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_quality_result_history_result_id', 'quality_result_history', ['result_id'])


def downgrade() -> None:
    op.drop_index('ix_quality_result_history_result_id', table_name='quality_result_history')
    op.drop_table('quality_result_history')
    with op.batch_alter_table('quality_result') as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('updated_by')
