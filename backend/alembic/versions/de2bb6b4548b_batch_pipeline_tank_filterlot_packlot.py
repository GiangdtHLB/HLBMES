"""batch_pipeline_tank_filterlot_packlot

Revision ID: de2bb6b4548b
Revises: bdffb11551d9
Create Date: 2026-08-30 00:00:00.000000

Pipeline thực thi MỚI cho "Mẻ sản xuất" (BatchExecution) theo blueprint 4 lớp — thêm 5 bảng
mới (batch_tank, batch_tank_link, batch_filter_lot, batch_filter_lot_source, batch_pack_lot).
Module Nấu-Lọc-Chiết cũ (ferment_record/filter_record/bottle_record...) không đổi gì — 2 hệ
chạy song song, không FK ràng buộc chéo (mirror quy ước "không FK constraint thật" của các
bảng danh mục/liên kết mềm trong các migration gần đây).
"""
from alembic import op
import sqlalchemy as sa


revision = 'de2bb6b4548b'
down_revision = 'bdffb11551d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'batch_tank',
        sa.Column('tank_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('tank_code', sa.Unicode(length=64), nullable=False),
        sa.Column('tank_year', sa.Integer(), nullable=False),
        sa.Column('tank_lm', sa.Unicode(length=255), nullable=True),
        sa.Column('product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('volume_hl', sa.Float(), nullable=False),
        sa.Column('on_hand', sa.Float(), nullable=False),
        sa.Column('status', sa.Unicode(length=255), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('quality_status', sa.Unicode(length=255), nullable=False),
        sa.UniqueConstraint('tank_year', 'tank_code', name='uq_batch_tank_year_code'),
    )
    op.create_index('ix_batch_tank_tank_code', 'batch_tank', ['tank_code'])
    op.create_index('ix_batch_tank_tank_year', 'batch_tank', ['tank_year'])
    op.create_index('ix_batch_tank_tank_lm', 'batch_tank', ['tank_lm'])
    op.create_index('ix_batch_tank_product_id', 'batch_tank', ['product_id'])

    op.create_table(
        'batch_tank_link',
        sa.Column('link_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('tank_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_id', sa.Unicode(length=64), nullable=False),
    )
    op.create_index('ix_batch_tank_link_tank_id', 'batch_tank_link', ['tank_id'])
    op.create_index('ix_batch_tank_link_batch_id', 'batch_tank_link', ['batch_id'])

    op.create_table(
        'batch_filter_lot',
        sa.Column('filter_lot_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('filter_lot_code', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_lot_year', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('beer_type_id', sa.Unicode(length=64), nullable=True),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('volume_hl', sa.Float(), nullable=False),
        sa.Column('on_hand', sa.Float(), nullable=False),
        sa.Column('status', sa.Unicode(length=255), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('quality_status', sa.Unicode(length=255), nullable=False),
        sa.UniqueConstraint('filter_lot_year', 'filter_lot_code', name='uq_batch_filter_lot_year_code'),
    )
    op.create_index('ix_batch_filter_lot_filter_lot_code', 'batch_filter_lot', ['filter_lot_code'])
    op.create_index('ix_batch_filter_lot_filter_lot_year', 'batch_filter_lot', ['filter_lot_year'])
    op.create_index('ix_batch_filter_lot_product_id', 'batch_filter_lot', ['product_id'])
    op.create_index('ix_batch_filter_lot_beer_type_id', 'batch_filter_lot', ['beer_type_id'])
    op.create_index('ix_batch_filter_lot_finished_product_id', 'batch_filter_lot', ['finished_product_id'])

    op.create_table(
        'batch_filter_lot_source',
        sa.Column('link_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('filter_lot_id', sa.Unicode(length=64), nullable=False),
        sa.Column('source_type', sa.Unicode(length=16), nullable=False),
        sa.Column('source_tank_id', sa.Unicode(length=64), nullable=True),
        sa.Column('source_filter_lot_id', sa.Unicode(length=64), nullable=True),
        sa.Column('reason', sa.UnicodeText(), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('volume_drawn', sa.Float(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_batch_filter_lot_source_filter_lot_id', 'batch_filter_lot_source', ['filter_lot_id'])
    op.create_index('ix_batch_filter_lot_source_source_tank_id', 'batch_filter_lot_source', ['source_tank_id'])
    op.create_index('ix_batch_filter_lot_source_source_filter_lot_id', 'batch_filter_lot_source',
                    ['source_filter_lot_id'])

    op.create_table(
        'batch_pack_lot',
        sa.Column('pack_lot_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('pack_lot_code', sa.Unicode(length=64), nullable=False),
        sa.Column('pack_lot_year', sa.Integer(), nullable=False),
        sa.Column('filter_lot_id', sa.Unicode(length=64), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('lot_no', sa.Unicode(length=255), nullable=True),
        sa.Column('line', sa.Unicode(length=255), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('quality_status', sa.Unicode(length=255), nullable=False),
        sa.UniqueConstraint('pack_lot_year', 'pack_lot_code', name='uq_batch_pack_lot_year_code'),
    )
    op.create_index('ix_batch_pack_lot_pack_lot_code', 'batch_pack_lot', ['pack_lot_code'])
    op.create_index('ix_batch_pack_lot_pack_lot_year', 'batch_pack_lot', ['pack_lot_year'])
    op.create_index('ix_batch_pack_lot_filter_lot_id', 'batch_pack_lot', ['filter_lot_id'])
    op.create_index('ix_batch_pack_lot_finished_product_id', 'batch_pack_lot', ['finished_product_id'])


def downgrade() -> None:
    op.drop_table('batch_pack_lot')
    op.drop_table('batch_filter_lot_source')
    op.drop_table('batch_filter_lot')
    op.drop_table('batch_tank_link')
    op.drop_table('batch_tank')
