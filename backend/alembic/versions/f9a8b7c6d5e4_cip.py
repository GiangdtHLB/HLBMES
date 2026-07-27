"""CIP (Cleaning-In-Place) — vệ sinh thiết bị: danh mục loại biểu mẫu + thiết bị, bản ghi
vệ sinh (bảng bước linh hoạt dạng JSON), và liên kết tay tới mẻ/lô sản xuất.

Revision ID: f9a8b7c6d5e4
Revises: e644f098d750
Create Date: 2026-07-26

4 bảng mới, không đổi bảng nào có sẵn:
- cip_form_type: danh mục loại biểu mẫu (mã BM giấy, khu vực, full/light).
- cip_equipment: danh mục thiết bị vệ sinh, gắn tuỳ chọn tới production_line (tank/dây
  chuyền) để tự lọc gợi ý theo đúng mã thiết bị mẻ/lô đó dùng.
- cip_record: 1 lần vệ sinh — steps lưu JSON linh hoạt (thêm/bớt dòng tự do).
- cip_link: gắn tay 1 cip_record với 1 mẻ/lô (scope_type/scope_id — cùng vocabulary
  brew_batch|ferment|filter|bottle đã dùng ở Hold/Deviation, xem services/quality.py).

Lưu ý: revision id ban đầu (a1b2c3d4e5f6) trùng với migration jobs đã có từ trước — đổi
sang f9a8b7c6d5e4 để tránh xung đột trong đồ thị Alembic.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f9a8b7c6d5e4'
down_revision = 'e644f098d750'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'cip_form_type',
        sa.Column('form_type_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('area', sa.Unicode(length=32), nullable=False),
        sa.Column('kind', sa.Unicode(length=16), nullable=False, server_default='full'),
        sa.Column('time_unit', sa.Unicode(length=16), nullable=False, server_default='phút'),
        sa.Column('temp_unit', sa.Unicode(length=16), nullable=False, server_default='°C'),
        sa.Column('conc_unit', sa.Unicode(length=16), nullable=False, server_default='%'),
        sa.Column('default_steps', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('form_type_id'),
    )
    op.create_index('ix_cip_form_type_code', 'cip_form_type', ['code'], unique=True)
    op.create_index('ix_cip_form_type_area', 'cip_form_type', ['area'])
    op.create_index('ix_cip_form_type_active', 'cip_form_type', ['active'])

    op.create_table(
        'cip_equipment',
        sa.Column('equipment_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('area', sa.Unicode(length=32), nullable=False),
        sa.Column('production_line_id', sa.Unicode(length=64), sa.ForeignKey('production_line.line_id'), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('equipment_id'),
    )
    op.create_index('ix_cip_equipment_code', 'cip_equipment', ['code'], unique=True)
    op.create_index('ix_cip_equipment_area', 'cip_equipment', ['area'])
    op.create_index('ix_cip_equipment_active', 'cip_equipment', ['active'])
    op.create_index('ix_cip_equipment_production_line_id', 'cip_equipment', ['production_line_id'])

    op.create_table(
        'cip_record',
        sa.Column('cip_id', sa.Unicode(length=64), nullable=False),
        sa.Column('cip_code', sa.Unicode(length=64), nullable=False),
        sa.Column('cip_year', sa.Integer(), nullable=False),
        sa.Column('form_type_id', sa.Unicode(length=64), sa.ForeignKey('cip_form_type.form_type_id'), nullable=False),
        sa.Column('equipment_id', sa.Unicode(length=64), sa.ForeignKey('cip_equipment.equipment_id'), nullable=False),
        sa.Column('batch_number', sa.Unicode(length=64), nullable=False, server_default=''),
        sa.Column('order_number', sa.Unicode(length=64), nullable=False, server_default=''),
        sa.Column('shift', sa.Unicode(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('performed_by', sa.Unicode(length=255), nullable=True),
        sa.Column('duty_officer', sa.Unicode(length=255), nullable=True),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('result', sa.Unicode(length=16), nullable=True),
        sa.Column('note', sa.Unicode(length=1000), nullable=True),
        sa.Column('checked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('cip_id'),
    )
    op.create_index('ix_cip_record_cip_code', 'cip_record', ['cip_code'], unique=True)
    op.create_index('ix_cip_record_cip_year', 'cip_record', ['cip_year'])
    op.create_index('ix_cip_record_form_type_id', 'cip_record', ['form_type_id'])
    op.create_index('ix_cip_record_equipment_id', 'cip_record', ['equipment_id'])
    op.create_index('ix_cip_record_started_at', 'cip_record', ['started_at'])
    op.create_index('ix_cip_record_batch_number', 'cip_record', ['batch_number'])
    op.create_index('ix_cip_record_order_number', 'cip_record', ['order_number'])

    op.create_table(
        'cip_link',
        sa.Column('link_id', sa.Unicode(length=64), nullable=False),
        sa.Column('cip_id', sa.Unicode(length=64), sa.ForeignKey('cip_record.cip_id'), nullable=False),
        sa.Column('scope_type', sa.Unicode(length=32), nullable=False),
        sa.Column('scope_id', sa.Unicode(length=64), nullable=False),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('link_id'),
        sa.UniqueConstraint('cip_id', 'scope_type', 'scope_id', name='uq_cip_link'),
    )
    op.create_index('ix_cip_link_cip_id', 'cip_link', ['cip_id'])
    op.create_index('ix_cip_link_scope_id', 'cip_link', ['scope_id'])


def downgrade() -> None:
    op.drop_table('cip_link')
    op.drop_table('cip_record')
    op.drop_table('cip_equipment')
    op.drop_table('cip_form_type')
