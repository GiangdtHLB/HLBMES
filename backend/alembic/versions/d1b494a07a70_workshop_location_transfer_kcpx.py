"""workshop location catalog + transfer kcpx request

Revision ID: d1b494a07a70
Revises: 8a09fb60a835
Create Date: 2026-08-20

- workshop_location: danh mục vị trí cất trong Kho phân xưởng (mirror material_location, dùng
  cho Kho công ty) — Kho phân xưởng trước đây chưa có danh mục vị trí riêng.
- material_lot.workshop_location_id: FK tới workshop_location, nullable, cột RIÊNG với
  location_id (chỉ dùng cho Kho công ty) — gán lúc Phân xưởng duyệt nhận điều chuyển.
- transfer_kcpx_request: đề nghị điều chuyển Kho công ty → Kho phân xưởng cho 1 lô đang có sẵn
  ở Kho công ty — CHƯA động tồn kho lúc tạo, chỉ khi Thủ kho phân xưởng duyệt (bắt buộc chọn
  workshop_location_id) mới thật sự chuyển; nếu vật tư có chỉ tiêu chất lượng bắt buộc, lô bị
  đưa về ON_HOLD ngay lúc tạo đề nghị để buộc KCS duyệt lại.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1b494a07a70'
down_revision = '8a09fb60a835'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workshop_location',
        sa.Column('loc_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('zone', sa.Unicode(length=120), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('loc_id'),
    )
    op.create_index('ix_workshop_location_code', 'workshop_location', ['code'], unique=True)

    with op.batch_alter_table('material_lot') as batch_op:
        batch_op.add_column(sa.Column('workshop_location_id', sa.Unicode(length=64), nullable=True))
        batch_op.create_foreign_key(
            'fk_material_lot_workshop_location_id', 'workshop_location', ['workshop_location_id'], ['loc_id'])
    op.create_index('ix_material_lot_workshop_location_id', 'material_lot', ['workshop_location_id'])

    op.create_table(
        'transfer_kcpx_request',
        sa.Column('request_id', sa.Unicode(length=64), nullable=False),
        sa.Column('request_code', sa.Unicode(length=64), nullable=False),
        sa.Column('lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False, server_default='kg'),
        sa.Column('reason', sa.UnicodeText(), nullable=True),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='pending'),
        sa.Column('movement_id', sa.Unicode(length=64), sa.ForeignKey('stock_movement.movement_id'), nullable=True),
        sa.Column('workshop_location_id', sa.Unicode(length=64),
                  sa.ForeignKey('workshop_location.loc_id'), nullable=True),
        sa.Column('reversed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approved_by', sa.Unicode(length=255), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by', sa.Unicode(length=255), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reject_reason', sa.UnicodeText(), nullable=True),
        sa.PrimaryKeyConstraint('request_id'),
    )
    op.create_index('ix_transfer_kcpx_request_request_code', 'transfer_kcpx_request', ['request_code'], unique=True)
    op.create_index('ix_transfer_kcpx_request_lot_id', 'transfer_kcpx_request', ['lot_id'])
    op.create_index('ix_transfer_kcpx_request_status', 'transfer_kcpx_request', ['status'])


def downgrade() -> None:
    op.drop_table('transfer_kcpx_request')
    op.drop_index('ix_material_lot_workshop_location_id', table_name='material_lot')
    with op.batch_alter_table('material_lot') as batch_op:
        batch_op.drop_constraint('fk_material_lot_workshop_location_id', type_='foreignkey')
        batch_op.drop_column('workshop_location_id')
    op.drop_index('ix_workshop_location_code', table_name='workshop_location')
    op.drop_table('workshop_location')
