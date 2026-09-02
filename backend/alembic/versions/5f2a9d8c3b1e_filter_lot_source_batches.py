"""filter_lot_source_batches

Revision ID: 5f2a9d8c3b1e
Revises: 4e8b6c1d9a2f
Create Date: 2026-08-31 00:00:00.000000

1 nguồn (BatchFilterLotSource) có thể có NHIỀU mẻ lọc (VD 1 tank thành phẩm cần 3 mẻ mới đầy)
— mirror FilterOrderTank (module Nấu-Lọc-Chiết cũ, dòng "template" vs dòng "mẻ"). Thêm bảng
batch_filter_lot_source_batch (1 dòng/mẻ, dich_nha_hl + nuoc_bai_khi_hl + is_final_batch +
ended_at); thêm v_dich_hl/nuoc_bai_khi_hl vào batch_filter_lot (tổng cộng dồn từ mọi mẻ); xóa
volume_drawn/ended_at khỏi batch_filter_lot_source (chuyển sang mẻ) — dữ liệu cũ (nếu có) được
di chuyển vào 1 dòng mẻ trước khi xóa cột, không mất dữ liệu.
"""
from alembic import op
import sqlalchemy as sa


revision = '5f2a9d8c3b1e'
down_revision = '4e8b6c1d9a2f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('batch_filter_lot', sa.Column('v_dich_hl', sa.Float(), nullable=True))
    op.add_column('batch_filter_lot', sa.Column('nuoc_bai_khi_hl', sa.Float(), nullable=True))
    op.execute("UPDATE batch_filter_lot SET v_dich_hl = volume_hl WHERE v_dich_hl IS NULL")
    op.execute("UPDATE batch_filter_lot SET nuoc_bai_khi_hl = 0 WHERE nuoc_bai_khi_hl IS NULL")

    op.create_table(
        'batch_filter_lot_source_batch',
        sa.Column('batch_link_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('source_link_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_seq_no', sa.Unicode(length=64), nullable=True),
        sa.Column('dich_nha_hl', sa.Float(), nullable=True),
        sa.Column('nuoc_bai_khi_hl', sa.Float(), nullable=True),
        sa.Column('is_final_batch', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_batch_filter_lot_source_batch_source_link_id',
                    'batch_filter_lot_source_batch', ['source_link_id'])

    # Di chuyển dữ liệu cũ (nếu bản ghi nào đã "Kết thúc" trước khi có bảng mẻ) thành 1 mẻ.
    conn = op.get_bind()
    import uuid
    rows = conn.execute(sa.text(
        "SELECT link_id, volume_drawn, ended_at FROM batch_filter_lot_source "
        "WHERE volume_drawn IS NOT NULL")).fetchall()
    for link_id, volume_drawn, ended_at in rows:
        conn.execute(sa.text(
            "INSERT INTO batch_filter_lot_source_batch "
            "(batch_link_id, source_link_id, dich_nha_hl, nuoc_bai_khi_hl, is_final_batch, ended_at, created_at) "
            "VALUES (:id, :src, :v, 0, 1, :ended, :ended)"
        ), {"id": uuid.uuid4().hex, "src": link_id, "v": volume_drawn, "ended": ended_at})

    with op.batch_alter_table('batch_filter_lot_source') as batch_op:
        batch_op.drop_column('volume_drawn')
        batch_op.drop_column('ended_at')


def downgrade() -> None:
    op.add_column('batch_filter_lot_source', sa.Column('volume_drawn', sa.Float(), nullable=True))
    op.add_column('batch_filter_lot_source', sa.Column('ended_at', sa.DateTime(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT source_link_id, SUM(COALESCE(dich_nha_hl, 0)), MAX(ended_at), "
        "SUM(CASE WHEN ended_at IS NULL THEN 1 ELSE 0 END) "
        "FROM batch_filter_lot_source_batch GROUP BY source_link_id")).fetchall()
    for source_link_id, total_v, max_ended, unfinished_count in rows:
        ended = None if unfinished_count else max_ended
        conn.execute(sa.text(
            "UPDATE batch_filter_lot_source SET volume_drawn = :v, ended_at = :ended WHERE link_id = :id"
        ), {"v": total_v, "ended": ended, "id": source_link_id})

    op.drop_index('ix_batch_filter_lot_source_batch_source_link_id', table_name='batch_filter_lot_source_batch')
    op.drop_table('batch_filter_lot_source_batch')
    op.drop_column('batch_filter_lot', 'nuoc_bai_khi_hl')
    op.drop_column('batch_filter_lot', 'v_dich_hl')
