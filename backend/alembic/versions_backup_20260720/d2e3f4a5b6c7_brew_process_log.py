"""Ghi chép nấu chi tiết theo mẻ — import Step Protocol (Braumat) + biểu mẫu KCS

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-10

- brew_process_step: 1 dòng / bước công đoạn tự động import từ file Step Protocol PDF
  (Braumat) của 1 mẻ (BrewBatch) — giữ nguyên toàn bộ tham số gốc (params_json) để
  không mất dữ liệu, tên tham số PLC tùy công thức/dây chuyền.
- brew_process_log: ghi chép nấu thủ công (khớp biểu mẫu giấy QT-KCS-QT-BM-04) — số
  liệu KCS đo tay (pH, %Bx) hoặc cân/định lượng thủ công (loại malt, hóa chất).
"""
from alembic import op
import sqlalchemy as sa

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'brew_process_step',
        sa.Column('step_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_id', sa.Unicode(length=64), sa.ForeignKey('brew_batch.batch_id'), nullable=False),
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
        sa.PrimaryKeyConstraint('step_id'),
    )
    op.create_index('ix_brew_process_step_batch_id', 'brew_process_step', ['batch_id'])
    op.create_index('ix_brew_process_step_unit', 'brew_process_step', ['unit'])

    op.create_table(
        'brew_process_log',
        sa.Column('log_id', sa.Unicode(length=64), nullable=False),
        sa.Column('batch_id', sa.Unicode(length=64), sa.ForeignKey('brew_batch.batch_id'), nullable=False),
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
        sa.PrimaryKeyConstraint('log_id'),
        sa.UniqueConstraint('batch_id'),
    )
    op.create_index('ix_brew_process_log_batch_id', 'brew_process_log', ['batch_id'])


def downgrade() -> None:
    op.drop_table('brew_process_log')
    op.drop_table('brew_process_step')
