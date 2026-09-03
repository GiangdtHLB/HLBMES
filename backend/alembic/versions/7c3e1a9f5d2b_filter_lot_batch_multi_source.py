"""filter_lot_batch_multi_source

Revision ID: 7c3e1a9f5d2b
Revises: 5f2a9d8c3b1e
Create Date: 2026-08-31 00:00:00.000000

Sửa lại mô hình mẻ lọc: 1 mẻ lọc (BatchFilterLotBatch) giờ thuộc về CẢ LÔ LỌC (không phải 1
nguồn riêng lẻ) — 1 mẻ có thể rút dịch CÙNG LÚC từ NHIỀU nguồn (VD phối tank lên men 01 + tank
02 trong 1 lần chạy máy), mỗi khoản rút theo từng nguồn nằm ở bảng mới
batch_filter_lot_batch_draw. Thay bảng batch_filter_lot_source_batch (mẻ thuộc 1 nguồn) bằng
batch_filter_lot_batch (mẻ thuộc lô lọc) + batch_filter_lot_batch_draw (khoản rút/nguồn/mẻ).

Dữ liệu cũ: mỗi dòng batch_filter_lot_source_batch (1 mẻ, 1 nguồn) được chuyển thành 1
batch_filter_lot_batch (giữ nguyên batch_link_id) + 1 batch_filter_lot_batch_draw tương ứng —
không gộp lại thành mẻ đa-nguồn (dữ liệu cũ vốn không có khái niệm đó), chỉ đổi hình dạng bảng,
tổng v_dich_hl/nuoc_bai_khi_hl/volume_hl/on_hand trên batch_filter_lot không đổi.
"""
from alembic import op
import sqlalchemy as sa


revision = '7c3e1a9f5d2b'
down_revision = '5f2a9d8c3b1e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'batch_filter_lot_batch',
        sa.Column('batch_link_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('filter_lot_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_seq_no', sa.Unicode(length=64), nullable=True),
        sa.Column('nuoc_bai_khi_hl', sa.Float(), nullable=True),
        sa.Column('is_final_batch', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_batch_filter_lot_batch_filter_lot_id',
                    'batch_filter_lot_batch', ['filter_lot_id'])

    op.create_table(
        'batch_filter_lot_batch_draw',
        sa.Column('draw_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('batch_link_id', sa.Unicode(length=64), nullable=False),
        sa.Column('source_link_id', sa.Unicode(length=64), nullable=False),
        sa.Column('dich_nha_hl', sa.Float(), nullable=True),
    )
    op.create_index('ix_batch_filter_lot_batch_draw_batch_link_id',
                    'batch_filter_lot_batch_draw', ['batch_link_id'])
    op.create_index('ix_batch_filter_lot_batch_draw_source_link_id',
                    'batch_filter_lot_batch_draw', ['source_link_id'])

    conn = op.get_bind()
    import uuid
    rows = conn.execute(sa.text(
        "SELECT sb.batch_link_id, sb.source_link_id, sb.batch_seq_no, sb.dich_nha_hl, "
        "sb.nuoc_bai_khi_hl, sb.is_final_batch, sb.ended_at, sb.created_at, s.filter_lot_id "
        "FROM batch_filter_lot_source_batch sb "
        "JOIN batch_filter_lot_source s ON s.link_id = sb.source_link_id")).fetchall()
    for (batch_link_id, source_link_id, batch_seq_no, dich_nha_hl, nuoc_bai_khi_hl,
         is_final_batch, ended_at, created_at, filter_lot_id) in rows:
        conn.execute(sa.text(
            "INSERT INTO batch_filter_lot_batch "
            "(batch_link_id, filter_lot_id, batch_seq_no, nuoc_bai_khi_hl, is_final_batch, ended_at, created_at) "
            "VALUES (:id, :flid, :seq, :daw, :final, :ended, :created)"
        ), {"id": batch_link_id, "flid": filter_lot_id, "seq": batch_seq_no, "daw": nuoc_bai_khi_hl,
            "final": is_final_batch, "ended": ended_at, "created": created_at})
        conn.execute(sa.text(
            "INSERT INTO batch_filter_lot_batch_draw (draw_id, batch_link_id, source_link_id, dich_nha_hl) "
            "VALUES (:id, :batch, :src, :v)"
        ), {"id": uuid.uuid4().hex, "batch": batch_link_id, "src": source_link_id, "v": dich_nha_hl})

    op.drop_index('ix_batch_filter_lot_source_batch_source_link_id', table_name='batch_filter_lot_source_batch')
    op.drop_table('batch_filter_lot_source_batch')


def downgrade() -> None:
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

    # Mẻ đa-nguồn (nếu có, tạo SAU khi nâng cấp) không có tương đương 1-nguồn thật sự — mỗi
    # khoản rút (draw) của 1 mẻ được tách thành 1 dòng "mẻ" riêng ở bảng cũ (chấp nhận mất khái
    # niệm "cùng 1 lần chạy máy" khi hạ cấp, nuoc_bai_khi_hl bị lặp lại trên mỗi dòng tách ra).
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT d.draw_id, d.batch_link_id, d.source_link_id, d.dich_nha_hl, "
        "b.batch_seq_no, b.nuoc_bai_khi_hl, b.is_final_batch, b.ended_at, b.created_at "
        "FROM batch_filter_lot_batch_draw d "
        "JOIN batch_filter_lot_batch b ON b.batch_link_id = d.batch_link_id")).fetchall()
    for (draw_id, batch_link_id, source_link_id, dich_nha_hl, batch_seq_no, nuoc_bai_khi_hl,
         is_final_batch, ended_at, created_at) in rows:
        conn.execute(sa.text(
            "INSERT INTO batch_filter_lot_source_batch "
            "(batch_link_id, source_link_id, batch_seq_no, dich_nha_hl, nuoc_bai_khi_hl, is_final_batch, ended_at, created_at) "
            "VALUES (:id, :src, :seq, :v, :daw, :final, :ended, :created)"
        ), {"id": draw_id, "src": source_link_id, "seq": batch_seq_no, "v": dich_nha_hl, "daw": nuoc_bai_khi_hl,
            "final": is_final_batch, "ended": ended_at, "created": created_at})

    op.drop_index('ix_batch_filter_lot_batch_draw_source_link_id', table_name='batch_filter_lot_batch_draw')
    op.drop_index('ix_batch_filter_lot_batch_draw_batch_link_id', table_name='batch_filter_lot_batch_draw')
    op.drop_table('batch_filter_lot_batch_draw')
    op.drop_index('ix_batch_filter_lot_batch_filter_lot_id', table_name='batch_filter_lot_batch')
    op.drop_table('batch_filter_lot_batch')
