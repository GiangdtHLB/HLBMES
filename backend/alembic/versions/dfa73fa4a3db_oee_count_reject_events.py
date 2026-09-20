"""oee_count_event + oee_reject_event — blueprint "OEE khung giờ bất kỳ" 2026-09-20

Revision ID: dfa73fa4a3db
Revises: 10cacc2b8540
Create Date: 2026-09-20

2 bảng mới lưu sự kiện thô có mốc thời gian (count_event = sản lượng tốt, reject_event =
phế phẩm), độc lập với downtime_event đã có sẵn start_at/end_at — cho phép tính OEE
(A×P×Q) cho BẤT KỲ khung [t1, t2] (giờ/ca/ngày/đang chạy) thay vì chỉ theo "ca" cố định như
OEERecord cũ. Không đổi/xóa bảng cũ nào — tính năng mới cộng thêm, song song."""
from alembic import op
import sqlalchemy as sa

revision = 'dfa73fa4a3db'
down_revision = '10cacc2b8540'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'oee_count_event',
        sa.Column('event_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('line', sa.Unicode(length=255), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('source', sa.Unicode(length=32), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('recorded_by', sa.Unicode(length=255), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_oee_count_event_line', 'oee_count_event', ['line'])
    op.create_index('ix_oee_count_event_ts', 'oee_count_event', ['ts'])

    op.create_table(
        'oee_reject_event',
        sa.Column('event_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('line', sa.Unicode(length=255), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('reason', sa.Unicode(length=255), nullable=True),
        sa.Column('source', sa.Unicode(length=32), nullable=False),
        sa.Column('recorded_by', sa.Unicode(length=255), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_oee_reject_event_line', 'oee_reject_event', ['line'])
    op.create_index('ix_oee_reject_event_ts', 'oee_reject_event', ['ts'])


def downgrade() -> None:
    op.drop_index('ix_oee_reject_event_ts', table_name='oee_reject_event')
    op.drop_index('ix_oee_reject_event_line', table_name='oee_reject_event')
    op.drop_table('oee_reject_event')
    op.drop_index('ix_oee_count_event_ts', table_name='oee_count_event')
    op.drop_index('ix_oee_count_event_line', table_name='oee_count_event')
    op.drop_table('oee_count_event')
