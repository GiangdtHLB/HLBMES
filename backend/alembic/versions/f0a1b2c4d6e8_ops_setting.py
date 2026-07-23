"""Cài đặt vận hành: ngưỡng dung sai thể tích cho phép Làm rỗng tank CCT/BBT

Revision ID: f0a1b2c4d6e8
Revises: e8f9a1b2c4d6
Create Date: 2026-07-21

- ops_setting: bảng mới, 1 dòng duy nhất (singleton) — empty_cct_tolerance_hl/
  empty_bbt_tolerance_hl, ngưỡng tồn dư (hl) tối đa được phép "Làm rỗng" thủ công cho tank
  lên men (CCT) và tank thành phẩm (BBT) khi tank vật lý đã cạn thật nhưng số liệu phần mềm
  còn lệch (hao hụt đo đạc/cặn/foam). Seed sẵn 1 dòng mặc định 2.0 hl mỗi loại.
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = 'f0a1b2c4d6e8'
down_revision = 'e8f9a1b2c4d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ops_setting',
        sa.Column('setting_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('empty_cct_tolerance_hl', sa.Float(), nullable=False),
        sa.Column('empty_bbt_tolerance_hl', sa.Float(), nullable=False),
        sa.Column('updated_by', sa.Unicode(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    conn = op.get_bind()
    table = sa.table('ops_setting', sa.column('setting_id'), sa.column('empty_cct_tolerance_hl'),
                     sa.column('empty_bbt_tolerance_hl'), sa.column('updated_by'), sa.column('updated_at'))
    conn.execute(table.insert().values(setting_id=str(uuid.uuid4()), empty_cct_tolerance_hl=2.0,
                                       empty_bbt_tolerance_hl=2.0, updated_by=None,
                                       updated_at=sa.func.now()))


def downgrade() -> None:
    op.drop_table('ops_setting')
