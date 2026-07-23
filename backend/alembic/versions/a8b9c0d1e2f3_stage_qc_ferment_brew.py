"""chỉ tiêu theo công đoạn sản xuất + liên kết mẻ nấu vào lô lên men

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-09

- stage_qc_group: gán nhóm chỉ tiêu chất lượng (qc_parameter_group) cho một công đoạn
  sản xuất (nau|len_men_chinh|len_men_phu|loc|chiet|thanh_pham), tuỳ chọn theo sản phẩm
  cụ thể (product_id để trống = áp dụng mọi sản phẩm) — cùng cơ chế material_qc_group.
- ferment_brew_link: liên kết thật nhiều mẻ nấu (brew_record) vào một lô lên men/tank
  (ferment_record), thay cho việc gõ tay vào ferment_record.batch_numbers.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a8b9c0d1e2f3'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stage_qc_group',
        sa.Column('link_id', sa.Unicode(length=64), nullable=False),
        sa.Column('stage', sa.Unicode(length=64), nullable=False),
        sa.Column('product_id', sa.Unicode(length=64), sa.ForeignKey('product.product_id'), nullable=True),
        sa.Column('group_id', sa.Unicode(length=64), sa.ForeignKey('qc_parameter_group.group_id'), nullable=False),
        sa.Column('mandatory', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('link_id'),
    )
    op.create_index('ix_stage_qc_group_stage', 'stage_qc_group', ['stage'])
    op.create_index('ix_stage_qc_group_product_id', 'stage_qc_group', ['product_id'])
    op.create_index('ix_stage_qc_group_group_id', 'stage_qc_group', ['group_id'])

    op.create_table(
        'ferment_brew_link',
        sa.Column('link_id', sa.Unicode(length=64), nullable=False),
        sa.Column('ferment_id', sa.Unicode(length=64), sa.ForeignKey('ferment_record.ferment_id'), nullable=False),
        sa.Column('brew_id', sa.Unicode(length=64), sa.ForeignKey('brew_record.brew_id'), nullable=False),
        sa.PrimaryKeyConstraint('link_id'),
    )
    op.create_index('ix_ferment_brew_link_ferment_id', 'ferment_brew_link', ['ferment_id'])
    op.create_index('ix_ferment_brew_link_brew_id', 'ferment_brew_link', ['brew_id'])


def downgrade() -> None:
    op.drop_table('ferment_brew_link')
    op.drop_table('stage_qc_group')
