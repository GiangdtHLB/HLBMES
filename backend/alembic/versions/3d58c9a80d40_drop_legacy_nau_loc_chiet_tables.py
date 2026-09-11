"""Xóa vật lý 19 bảng của module "Nấu-Lọc-Chiết" cũ — đã thay thế hoàn toàn bởi pipeline
"Mẻ sản xuất" (models/batch_pipeline.py: BatchExecution→BatchTank→BatchFilterLot→
BatchPackLot).

Revision ID: 3d58c9a80d40
Revises: a4d6f89ff65e
Create Date: 2026-09-11

Phạm vi xóa (đúng 19 model đã gỡ khỏi models/brewing.py — xem app/models/brewing.py hiện
tại, chỉ còn BrewOrder/BrewOrderMaterialLine/OpsSetting): material_receipt, brew_record,
brew_batch, brew_process_step, brew_process_log, brew_material_usage, ferment_record,
ferment_brew_link, ferment_process_log, ferment_daily_reading, filter_master_order,
filter_order, filter_order_tank, filter_order_material_line, filter_record,
filter_material_usage, bottle_material_usage, bottle_record, stage_indicator.

KHÔNG đụng tới: brew_order, brew_order_material_line, ops_setting (BrewOrder vẫn là tính
năng "Lệnh nấu" đang dùng, giờ chỉ còn liên kết với pipeline "Mẻ sản xuất" qua
BatchExecution.order_id/WorkOrder.brew_order_id — không còn qua brew_record nữa; OpsSetting
là cấu hình chia sẻ, không thuộc phạm vi module cũ).

Cột downgrade() dựng lại ĐÚNG schema thật đang có trong CSDL (đối chiếu qua reflection trên
CSDL dev, KHÔNG chỉ theo model Python hiện có trong lịch sử git) — brew_process_log vẫn còn
~35 cột riêng lẻ (rc_*/mt_*/lt_*/wk_*/whp_*) từ trước khi refactor sang `manual_json`
(migration f1a2b3c4d5e6_brew_form_spec.py chỉ ADD manual_json, chưa từng DROP các cột cũ) —
downgrade() ở đây giữ nguyên các cột "mồ côi" đó để khớp đúng những gì thực sự tồn tại trong
CSDL, không chỉ những gì model Python còn khai báo.

QUAN TRỌNG: đây là DDL phá hủy — xóa cả bảng lẫn TOÀN BỘ dữ liệu bên trong (nếu có). Backup
database trước khi chạy trên production. downgrade() chỉ dựng lại ĐÚNG SCHEMA (cột/FK/index)
theo bản cuối cùng trước khi các bảng này bị xóa — KHÔNG khôi phục lại dữ liệu đã mất.
"""
from alembic import op
import sqlalchemy as sa


revision = '3d58c9a80d40'
down_revision = 'a4d6f89ff65e'
branch_labels = None
depends_on = None

# Thứ tự XÓA — con trước cha, tính theo toàn bộ FK thật giữa 19 bảng này với nhau (kể cả
# self-reference filter_record.source_filter_id -> filter_record.filter_id, xóa gọn trong 1
# câu DROP TABLE nên không cần xử lý riêng). KHÔNG tự ý đổi thứ tự nếu không kiểm tra lại FK.
DROP_ORDER = [
    "brew_process_step", "brew_process_log", "brew_material_usage",
    "bottle_material_usage", "bottle_record",
    "filter_material_usage", "filter_order_tank", "filter_order_material_line",
    "filter_record", "filter_order", "filter_master_order",
    "ferment_brew_link", "ferment_process_log", "ferment_daily_reading", "ferment_record",
    "brew_batch", "brew_record",
    "material_receipt", "stage_indicator",
]


def upgrade() -> None:
    for table in DROP_ORDER:
        op.drop_table(table)


def downgrade() -> None:
    op.create_table(
        'stage_indicator',
        sa.Column('indicator_id', sa.Unicode(length=64), nullable=False),
        sa.Column('stage', sa.Unicode(length=255), nullable=False),
        sa.Column('scope_code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('unit', sa.Unicode(length=255), nullable=True),
        sa.Column('value', sa.Float(), nullable=True),
        sa.Column('value_text', sa.Unicode(length=255), nullable=True),
        sa.Column('warning', sa.Unicode(length=255), nullable=True),
        sa.Column('analyst', sa.Unicode(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('indicator_id'),
    )
    op.create_index(op.f('ix_stage_indicator_scope_code'), 'stage_indicator', ['scope_code'])
    op.create_index(op.f('ix_stage_indicator_stage'), 'stage_indicator', ['stage'])

    op.create_table(
        'material_receipt',
        sa.Column('receipt_id', sa.Unicode(length=64), nullable=False),
        sa.Column('mskt', sa.Unicode(length=255), nullable=False),
        sa.Column('receipt_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('material_name', sa.Unicode(length=255), nullable=False),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_kcs', sa.Unicode(length=255), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False),
        sa.Column('location', sa.Unicode(length=255), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('supplier', sa.Unicode(length=255), nullable=True),
        sa.Column('has_indicators', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('receipt_id'),
    )
    op.create_index(op.f('ix_material_receipt_mskt'), 'material_receipt', ['mskt'])
    op.create_index(op.f('ix_material_receipt_receipt_date'), 'material_receipt', ['receipt_date'])

    op.create_table(
        'brew_record',
        sa.Column('brew_id', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_code', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('wort_type', sa.Unicode(length=255), nullable=False),
        sa.Column('volume_hl', sa.Float(), nullable=False),
        sa.Column('original_extract', sa.Float(), nullable=True),
        sa.Column('plato', sa.Float(), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('brew_order_id', sa.Unicode(length=64), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('brew_year', sa.Integer(), nullable=False),
        sa.Column('work_order_id', sa.Unicode(length=64), nullable=True),
        sa.ForeignKeyConstraint(['brew_order_id'], ['brew_order.brew_order_id']),
        sa.ForeignKeyConstraint(['product_id'], ['product.product_id']),
        sa.ForeignKeyConstraint(['work_order_id'], ['work_order.wo_id']),
        sa.PrimaryKeyConstraint('brew_id'),
        sa.UniqueConstraint('brew_year', 'brew_code', name='uq_brew_record_year_code'),
    )
    op.create_index(op.f('ix_brew_record_brew_code'), 'brew_record', ['brew_code'])
    op.create_index(op.f('ix_brew_record_brew_date'), 'brew_record', ['brew_date'])
    op.create_index(op.f('ix_brew_record_brew_order_id'), 'brew_record', ['brew_order_id'])
    op.create_index(op.f('ix_brew_record_brew_year'), 'brew_record', ['brew_year'])
    op.create_index(op.f('ix_brew_record_work_order_id'), 'brew_record', ['work_order_id'])

    op.create_table(
        'brew_batch',
        sa.Column('batch_id', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_code', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_year', sa.Integer(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quality_status', sa.Unicode(length=255), nullable=False),
        sa.Column('line_id', sa.Unicode(length=64), nullable=True),
        sa.ForeignKeyConstraint(['brew_id'], ['brew_record.brew_id']),
        sa.PrimaryKeyConstraint('batch_id'),
        sa.UniqueConstraint('batch_year', 'batch_code', name='uq_brew_batch_year_code'),
    )
    op.create_index(op.f('ix_brew_batch_batch_code'), 'brew_batch', ['batch_code'])
    op.create_index(op.f('ix_brew_batch_batch_year'), 'brew_batch', ['batch_year'])
    op.create_index(op.f('ix_brew_batch_brew_id'), 'brew_batch', ['brew_id'])
    op.create_index(op.f('ix_brew_batch_line_id'), 'brew_batch', ['line_id'])

    op.create_table(
        'ferment_record',
        sa.Column('ferment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('lm_code', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_code', sa.Unicode(length=64), nullable=True),
        sa.Column('brew_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('kt_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('batch_numbers', sa.UnicodeText(), nullable=True),
        sa.Column('wort_type', sa.Unicode(length=255), nullable=False),
        sa.Column('yeast_gen', sa.Unicode(length=255), nullable=True),
        sa.Column('tank_lm', sa.Unicode(length=255), nullable=False),
        sa.Column('volume_hl', sa.Float(), nullable=False),
        sa.Column('on_hand_cct', sa.Float(), nullable=False),
        sa.Column('status', sa.Unicode(length=255), nullable=False),
        sa.Column('ferment_days', sa.Unicode(length=255), nullable=True),
        sa.Column('product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('qc_approved', sa.Boolean(), nullable=False),
        sa.Column('qc_approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('qc_approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quality_status', sa.Unicode(length=255), nullable=False),
        sa.Column('ferment_year', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.product_id']),
        sa.PrimaryKeyConstraint('ferment_id'),
        sa.UniqueConstraint('ferment_year', 'lm_code', name='uq_ferment_record_year_code'),
    )
    op.create_index(op.f('ix_ferment_record_brew_code'), 'ferment_record', ['brew_code'])
    op.create_index(op.f('ix_ferment_record_ferment_year'), 'ferment_record', ['ferment_year'])
    op.create_index(op.f('ix_ferment_record_lm_code'), 'ferment_record', ['lm_code'])
    op.create_index(op.f('ix_ferment_record_tank_lm'), 'ferment_record', ['tank_lm'])

    op.create_table(
        'ferment_daily_reading',
        sa.Column('reading_id', sa.Unicode(length=64), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('day_no', sa.Integer(), nullable=False),
        sa.Column('reading_date', sa.Unicode(length=32), nullable=True),
        sa.Column('nhiet_do_c', sa.Float(), nullable=True),
        sa.Column('do_s', sa.Float(), nullable=True),
        sa.Column('mat_do_tb', sa.Float(), nullable=True),
        sa.Column('measured_by', sa.Unicode(length=255), nullable=True),
        sa.Column('measured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('kcs', sa.Unicode(length=64), nullable=True),
        sa.Column('kcs_by', sa.Unicode(length=255), nullable=True),
        sa.Column('kcs_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('truc_ca', sa.Unicode(length=64), nullable=True),
        sa.Column('truc_ca_by', sa.Unicode(length=255), nullable=True),
        sa.Column('truc_ca_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['ferment_id'], ['ferment_record.ferment_id']),
        sa.PrimaryKeyConstraint('reading_id'),
        sa.UniqueConstraint('ferment_id', 'day_no', name='uq_ferment_daily_reading_day'),
    )
    op.create_index(op.f('ix_ferment_daily_reading_ferment_id'), 'ferment_daily_reading', ['ferment_id'])

    op.create_table(
        'ferment_process_log',
        sa.Column('log_id', sa.Unicode(length=64), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('manual_json', sa.UnicodeText(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('updated_by', sa.Unicode(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['ferment_id'], ['ferment_record.ferment_id']),
        sa.PrimaryKeyConstraint('log_id'),
    )
    op.create_index(op.f('ix_ferment_process_log_ferment_id'), 'ferment_process_log', ['ferment_id'])

    op.create_table(
        'ferment_brew_link',
        sa.Column('link_id', sa.Unicode(length=64), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_id', sa.Unicode(length=64), nullable=False),
        sa.ForeignKeyConstraint(['brew_id'], ['brew_record.brew_id']),
        sa.ForeignKeyConstraint(['ferment_id'], ['ferment_record.ferment_id']),
        sa.PrimaryKeyConstraint('link_id'),
    )
    op.create_index(op.f('ix_ferment_brew_link_brew_id'), 'ferment_brew_link', ['brew_id'])
    op.create_index(op.f('ix_ferment_brew_link_ferment_id'), 'ferment_brew_link', ['ferment_id'])

    op.create_table(
        'filter_master_order',
        sa.Column('filter_master_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('order_year', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('filter_master_order_id'),
        sa.UniqueConstraint('order_year', 'order_code', name='uq_filter_master_order_year_code'),
    )
    op.create_index(op.f('ix_filter_master_order_order_code'), 'filter_master_order', ['order_code'])
    op.create_index(op.f('ix_filter_master_order_order_year'), 'filter_master_order', ['order_year'])

    op.create_table(
        'filter_order',
        sa.Column('filter_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('blend_mode', sa.Unicode(length=32), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('kcs_lot_no', sa.Unicode(length=255), nullable=True),
        sa.Column('planned_volume_hl', sa.Float(), nullable=False),
        sa.Column('volume_tolerance_hl', sa.Float(), nullable=False),
        sa.Column('master_order_id', sa.Unicode(length=64), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('beer_type_id', sa.Unicode(length=64), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('order_year', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['beer_type_id'], ['beer_type.beer_type_id']),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.ForeignKeyConstraint(['master_order_id'], ['filter_master_order.filter_master_order_id']),
        sa.PrimaryKeyConstraint('filter_order_id'),
        sa.UniqueConstraint('order_year', 'order_code', name='uq_filter_order_year_code'),
    )
    op.create_index(op.f('ix_filter_order_beer_type_id'), 'filter_order', ['beer_type_id'])
    op.create_index(op.f('ix_filter_order_finished_product_id'), 'filter_order', ['finished_product_id'])
    op.create_index(op.f('ix_filter_order_master_order_id'), 'filter_order', ['master_order_id'])
    op.create_index(op.f('ix_filter_order_order_code'), 'filter_order', ['order_code'])
    op.create_index(op.f('ix_filter_order_order_year'), 'filter_order', ['order_year'])

    op.create_table(
        'filter_record',
        sa.Column('filter_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_code', sa.Unicode(length=64), nullable=False),
        sa.Column('brew_code', sa.Unicode(length=64), nullable=True),
        sa.Column('lot_loc', sa.Unicode(length=255), nullable=True),
        sa.Column('filter_phoi_code', sa.Unicode(length=64), nullable=True),
        sa.Column('filter_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('filter_type', sa.Unicode(length=255), nullable=False),
        sa.Column('wort_type', sa.Unicode(length=255), nullable=True),
        sa.Column('from_cct', sa.Unicode(length=255), nullable=True),
        sa.Column('v_dich_hl', sa.Float(), nullable=False),
        sa.Column('beer_type', sa.Unicode(length=255), nullable=False),
        sa.Column('v_beer_hl', sa.Float(), nullable=False),
        sa.Column('to_bbt', sa.Unicode(length=255), nullable=True),
        sa.Column('status', sa.Unicode(length=255), nullable=False),
        sa.Column('on_hand_bbt', sa.Float(), nullable=False),
        sa.Column('has_indicators', sa.Boolean(), nullable=False),
        sa.Column('has_nvl', sa.Boolean(), nullable=False),
        sa.Column('product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('ferment_id', sa.Unicode(length=64), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('nuoc_bai_khi_hl', sa.Float(), nullable=False),
        sa.Column('filter_order_id', sa.Unicode(length=64), nullable=True),
        sa.Column('qc_approved', sa.Boolean(), nullable=False),
        sa.Column('qc_approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('qc_approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('beer_type_id', sa.Unicode(length=64), nullable=True),
        sa.Column('source_filter_id', sa.Unicode(length=64), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('quality_status', sa.Unicode(length=255), nullable=False),
        sa.Column('batch_number', sa.Unicode(length=255), nullable=True),
        sa.Column('order_number', sa.Unicode(length=255), nullable=True),
        sa.Column('filter_year', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['beer_type_id'], ['beer_type.beer_type_id']),
        sa.ForeignKeyConstraint(['ferment_id'], ['ferment_record.ferment_id']),
        sa.ForeignKeyConstraint(['filter_order_id'], ['filter_order.filter_order_id']),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.ForeignKeyConstraint(['product_id'], ['product.product_id']),
        sa.ForeignKeyConstraint(['source_filter_id'], ['filter_record.filter_id']),
        sa.PrimaryKeyConstraint('filter_id'),
        sa.UniqueConstraint('filter_year', 'filter_code', name='uq_filter_record_year_code'),
    )
    op.create_index(op.f('ix_filter_record_batch_number'), 'filter_record', ['batch_number'])
    op.create_index(op.f('ix_filter_record_beer_type_id'), 'filter_record', ['beer_type_id'])
    op.create_index(op.f('ix_filter_record_ferment_id'), 'filter_record', ['ferment_id'])
    op.create_index(op.f('ix_filter_record_filter_code'), 'filter_record', ['filter_code'])
    op.create_index(op.f('ix_filter_record_filter_date'), 'filter_record', ['filter_date'])
    op.create_index(op.f('ix_filter_record_filter_order_id'), 'filter_record', ['filter_order_id'])
    op.create_index(op.f('ix_filter_record_filter_year'), 'filter_record', ['filter_year'])
    op.create_index(op.f('ix_filter_record_finished_product_id'), 'filter_record', ['finished_product_id'])
    op.create_index(op.f('ix_filter_record_order_number'), 'filter_record', ['order_number'])
    op.create_index(op.f('ix_filter_record_source_filter_id'), 'filter_record', ['source_filter_id'])
    op.create_index(op.f('ix_filter_record_to_bbt'), 'filter_record', ['to_bbt'])

    op.create_table(
        'filter_order_material_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('material_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=True),
        sa.Column('uom', sa.Unicode(length=64), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('stock_company_snapshot', sa.Float(), nullable=True),
        sa.Column('stock_workshop_snapshot', sa.Float(), nullable=True),
        sa.Column('material_group_code', sa.Unicode(length=64), nullable=True),
        sa.ForeignKeyConstraint(['filter_order_id'], ['filter_order.filter_order_id']),
        sa.ForeignKeyConstraint(['material_id'], ['material.material_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_filter_order_material_line_filter_order_id'), 'filter_order_material_line', ['filter_order_id'])
    op.create_index(op.f('ix_filter_order_material_line_material_id'), 'filter_order_material_line', ['material_id'])

    op.create_table(
        'filter_order_tank',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_order_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_id', sa.Unicode(length=64), nullable=True),
        sa.Column('tank_type', sa.Unicode(length=16), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), nullable=True),
        sa.Column('source_bbt_code', sa.Unicode(length=255), nullable=True),
        sa.Column('source_filter_id', sa.Unicode(length=64), nullable=True),
        sa.Column('reason', sa.UnicodeText(), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('planned_v_dich_hl', sa.Float(), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('v_dich_hl', sa.Float(), nullable=True),
        sa.Column('nuoc_bai_khi_hl', sa.Float(), nullable=True),
        sa.Column('batch_seq_no', sa.Unicode(length=64), nullable=True),
        sa.Column('is_final_batch', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['ferment_id'], ['ferment_record.ferment_id']),
        sa.ForeignKeyConstraint(['filter_id'], ['filter_record.filter_id']),
        sa.ForeignKeyConstraint(['filter_order_id'], ['filter_order.filter_order_id']),
        sa.ForeignKeyConstraint(['source_filter_id'], ['filter_record.filter_id']),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index(op.f('ix_filter_order_tank_ferment_id'), 'filter_order_tank', ['ferment_id'])
    op.create_index(op.f('ix_filter_order_tank_filter_id'), 'filter_order_tank', ['filter_id'])
    op.create_index(op.f('ix_filter_order_tank_filter_order_id'), 'filter_order_tank', ['filter_order_id'])
    op.create_index(op.f('ix_filter_order_tank_source_bbt_code'), 'filter_order_tank', ['source_bbt_code'])
    op.create_index(op.f('ix_filter_order_tank_source_filter_id'), 'filter_order_tank', ['source_filter_id'])

    op.create_table(
        'filter_material_usage',
        sa.Column('usage_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_id', sa.Unicode(length=64), nullable=False),
        sa.Column('receipt_id', sa.Unicode(length=64), nullable=True),
        sa.Column('lot_id', sa.Unicode(length=64), nullable=True),
        sa.Column('movement_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=False),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lot_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['filter_id'], ['filter_record.filter_id']),
        sa.ForeignKeyConstraint(['lot_id'], ['material_lot.lot_id']),
        sa.ForeignKeyConstraint(['movement_id'], ['stock_movement.movement_id']),
        sa.ForeignKeyConstraint(['receipt_id'], ['material_receipt.receipt_id']),
        sa.PrimaryKeyConstraint('usage_id'),
    )
    op.create_index(op.f('ix_filter_material_usage_filter_id'), 'filter_material_usage', ['filter_id'])
    op.create_index(op.f('ix_filter_material_usage_lot_id'), 'filter_material_usage', ['lot_id'])

    op.create_table(
        'bottle_record',
        sa.Column('bottle_id', sa.Unicode(length=64), nullable=False),
        sa.Column('bottle_code', sa.Unicode(length=64), nullable=False),
        sa.Column('filter_code', sa.Unicode(length=64), nullable=True),
        sa.Column('bottle_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('beer_type', sa.Unicode(length=255), nullable=False),
        sa.Column('lot_no', sa.Unicode(length=255), nullable=True),
        sa.Column('v_cap_chiet_hl', sa.Float(), nullable=False),
        sa.Column('from_bbt', sa.Unicode(length=255), nullable=True),
        sa.Column('line', sa.Unicode(length=255), nullable=True),
        sa.Column('ca1', sa.Float(), nullable=False),
        sa.Column('ca2', sa.Float(), nullable=False),
        sa.Column('ca3', sa.Float(), nullable=False),
        sa.Column('stocked', sa.Boolean(), nullable=False),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('has_indicators', sa.Boolean(), nullable=False),
        sa.Column('has_nvl', sa.Boolean(), nullable=False),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('finished_product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('filter_id', sa.Unicode(length=64), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('beer_type_id', sa.Unicode(length=64), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quality_status', sa.Unicode(length=255), nullable=False),
        sa.Column('bottle_year', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['beer_type_id'], ['beer_type.beer_type_id']),
        sa.ForeignKeyConstraint(['filter_id'], ['filter_record.filter_id']),
        sa.ForeignKeyConstraint(['finished_product_id'], ['finished_product.finished_product_id']),
        sa.ForeignKeyConstraint(['product_id'], ['product.product_id']),
        sa.PrimaryKeyConstraint('bottle_id'),
        sa.UniqueConstraint('bottle_year', 'bottle_code', name='uq_bottle_record_year_code'),
    )
    op.create_index(op.f('ix_bottle_record_beer_type_id'), 'bottle_record', ['beer_type_id'])
    op.create_index(op.f('ix_bottle_record_bottle_code'), 'bottle_record', ['bottle_code'])
    op.create_index(op.f('ix_bottle_record_bottle_date'), 'bottle_record', ['bottle_date'])
    op.create_index(op.f('ix_bottle_record_bottle_year'), 'bottle_record', ['bottle_year'])
    op.create_index(op.f('ix_bottle_record_filter_code'), 'bottle_record', ['filter_code'])
    op.create_index(op.f('ix_bottle_record_filter_id'), 'bottle_record', ['filter_id'])
    op.create_index(op.f('ix_bottle_record_finished_product_id'), 'bottle_record', ['finished_product_id'])
    op.create_index(op.f('ix_bottle_record_from_bbt'), 'bottle_record', ['from_bbt'])

    op.create_table(
        'bottle_material_usage',
        sa.Column('usage_id', sa.Unicode(length=64), nullable=False),
        sa.Column('bottle_id', sa.Unicode(length=64), nullable=False),
        sa.Column('lot_id', sa.Unicode(length=64), nullable=True),
        sa.Column('movement_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=False),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('lot_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['bottle_id'], ['bottle_record.bottle_id']),
        sa.ForeignKeyConstraint(['lot_id'], ['material_lot.lot_id']),
        sa.ForeignKeyConstraint(['movement_id'], ['stock_movement.movement_id']),
        sa.PrimaryKeyConstraint('usage_id'),
    )
    op.create_index(op.f('ix_bottle_material_usage_bottle_id'), 'bottle_material_usage', ['bottle_id'])
    op.create_index(op.f('ix_bottle_material_usage_lot_id'), 'bottle_material_usage', ['lot_id'])

    op.create_table(
        'brew_material_usage',
        sa.Column('usage_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_id', sa.Unicode(length=64), nullable=False),
        sa.Column('receipt_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=False),
        sa.Column('lot_pm', sa.Unicode(length=255), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lot_id', sa.Unicode(length=64), nullable=True),
        sa.Column('movement_id', sa.Unicode(length=64), nullable=True),
        sa.Column('lot_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fifo_ok', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['batch_id'], ['brew_batch.batch_id']),
        sa.ForeignKeyConstraint(['lot_id'], ['material_lot.lot_id']),
        sa.ForeignKeyConstraint(['movement_id'], ['stock_movement.movement_id']),
        sa.ForeignKeyConstraint(['receipt_id'], ['material_receipt.receipt_id']),
        sa.PrimaryKeyConstraint('usage_id'),
    )
    op.create_index(op.f('ix_brew_material_usage_batch_id'), 'brew_material_usage', ['batch_id'])
    op.create_index(op.f('ix_brew_material_usage_lot_id'), 'brew_material_usage', ['lot_id'])
    op.create_index(op.f('ix_brew_material_usage_receipt_id'), 'brew_material_usage', ['receipt_id'])

    op.create_table(
        'brew_process_log',
        sa.Column('log_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_id', sa.Unicode(length=64), nullable=False),
        sa.Column('braumat_order_number', sa.Unicode(length=64), nullable=True),
        sa.Column('braumat_recipe', sa.Unicode(length=255), nullable=True),
        sa.Column('rc_gao_truoc_kg', sa.Float(), nullable=True),
        sa.Column('rc_gao_sau_kg', sa.Float(), nullable=True),
        sa.Column('rc_nuoc_hl', sa.Float(), nullable=True),
        sa.Column('rc_ph_nuoc', sa.Float(), nullable=True),
        sa.Column('rc_termamyl_ml', sa.Float(), nullable=True),
        sa.Column('rc_toc_do_khuay', sa.Float(), nullable=True),
        sa.Column('rc_ph', sa.Float(), nullable=True),
        sa.Column('mt_nghien_malt_uot_truoc_kg', sa.Float(), nullable=True),
        sa.Column('mt_nghien_malt_uot_sau_kg', sa.Float(), nullable=True),
        sa.Column('mt_malt_anh_kg', sa.Float(), nullable=True),
        sa.Column('mt_malt_duc_kg', sa.Float(), nullable=True),
        sa.Column('mt_malt_y_kg', sa.Float(), nullable=True),
        sa.Column('mt_neutrase_ml', sa.Float(), nullable=True),
        sa.Column('mt_ultraprime_ml', sa.Float(), nullable=True),
        sa.Column('mt_attenuazym_pro_ml', sa.Float(), nullable=True),
        sa.Column('mt_cacl2_kg', sa.Float(), nullable=True),
        sa.Column('mt_caso4_kg', sa.Float(), nullable=True),
        sa.Column('mt_nuoc_hl', sa.Float(), nullable=True),
        sa.Column('mt_ph_nuoc', sa.Float(), nullable=True),
        sa.Column('lt_percent_bx_ket_thuc_loc_trang', sa.Float(), nullable=True),
        sa.Column('lt_kiem_tra_bao_muc', sa.Boolean(), nullable=True),
        sa.Column('wk_hoa_cao_kg', sa.Float(), nullable=True),
        sa.Column('wk_hoa_vien_duc_kg', sa.Float(), nullable=True),
        sa.Column('wk_rho_my_kg', sa.Float(), nullable=True),
        sa.Column('wk_znso4_g', sa.Float(), nullable=True),
        sa.Column('wk_ph', sa.Float(), nullable=True),
        sa.Column('wk_percent_bx_ket_thuc_dun_hoa', sa.Float(), nullable=True),
        sa.Column('whp_thoi_gian_lang_phut', sa.Float(), nullable=True),
        sa.Column('whp_t0_chuyen_dich', sa.Float(), nullable=True),
        sa.Column('whp_oxy_lit_phut', sa.Float(), nullable=True),
        sa.Column('whp_percent_bx', sa.Float(), nullable=True),
        sa.Column('whp_tong_luong_dich_hl', sa.Float(), nullable=True),
        sa.Column('whp_ph', sa.Float(), nullable=True),
        sa.Column('whp_axit', sa.Float(), nullable=True),
        sa.Column('whp_maturex_pro_added', sa.Boolean(), nullable=True),
        sa.Column('whp_brew_clarex_added', sa.Boolean(), nullable=True),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('updated_by', sa.Unicode(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('manual_json', sa.UnicodeText(), nullable=True),
        sa.Column('braumat_batch_number', sa.Unicode(length=64), nullable=True),
        sa.ForeignKeyConstraint(['batch_id'], ['brew_batch.batch_id']),
        sa.PrimaryKeyConstraint('log_id'),
    )
    op.create_index(op.f('ix_brew_process_log_batch_id'), 'brew_process_log', ['batch_id'])

    op.create_table(
        'brew_process_step',
        sa.Column('step_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_id', sa.Unicode(length=64), nullable=False),
        sa.Column('unit', sa.Unicode(length=255), nullable=False),
        sa.Column('step_no', sa.Integer(), nullable=False),
        sa.Column('eop', sa.Unicode(length=64), nullable=True),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('elapsed_actual', sa.Unicode(length=32), nullable=True),
        sa.Column('params_json', sa.UnicodeText(), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('imported_by', sa.Unicode(length=255), nullable=True),
        sa.ForeignKeyConstraint(['batch_id'], ['brew_batch.batch_id']),
        sa.PrimaryKeyConstraint('step_id'),
    )
    op.create_index(op.f('ix_brew_process_step_batch_id'), 'brew_process_step', ['batch_id'])
    op.create_index(op.f('ix_brew_process_step_unit'), 'brew_process_step', ['unit'])
