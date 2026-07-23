"""đề nghị nhận kho (material_request)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-08

Phân xưởng tạo đề nghị nhận kho (chọn vật tư/SL, có thể chọn lô ưu tiên);
thủ kho công ty duyệt (transfer lô sang Kho phân xưởng) hoặc từ chối.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'material_request',
        sa.Column('request_id', sa.Unicode(length=64), nullable=False),
        sa.Column('request_code', sa.Unicode(length=64), nullable=False),
        sa.Column('material_id', sa.Unicode(length=64), sa.ForeignKey('material.material_id'), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False, server_default='kg'),
        sa.Column('preferred_lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=True),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='pending'),
        sa.Column('note', sa.UnicodeText(), nullable=True),
        sa.Column('requested_by', sa.Unicode(length=255), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fulfilled_lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=True),
        sa.Column('fulfilled_qty', sa.Float(), nullable=True),
        sa.Column('fulfilled_by', sa.Unicode(length=255), nullable=True),
        sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.UnicodeText(), nullable=True),
        sa.PrimaryKeyConstraint('request_id'),
        sa.UniqueConstraint('request_code'),
    )
    op.create_index('ix_material_request_material_id', 'material_request', ['material_id'])
    op.create_index('ix_material_request_status', 'material_request', ['status'])


def downgrade() -> None:
    op.drop_table('material_request')
