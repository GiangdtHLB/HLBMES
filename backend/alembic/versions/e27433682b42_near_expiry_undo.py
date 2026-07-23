"""Bia cận date: hỗ trợ Hoàn tác bản khai nhập

Revision ID: e27433682b42
Revises: f1a2b3c4d5ea
Create Date: 2026-07-22

- near_expiry_entry.unit_codes (Text, nullable): unit_code các vỉ/keg do lần khai báo
  direction="in" tạo ra (nối dấu phẩy) — cho phép Hoàn tác xoá đúng các đơn vị đó.
- near_expiry_entry.reversed (Boolean, default False): đánh dấu bản khai đã được hoàn tác.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e27433682b42'
down_revision = 'f1a2b3c4d5ea'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('near_expiry_entry', sa.Column('unit_codes', sa.UnicodeText(), nullable=True))
    op.add_column('near_expiry_entry', sa.Column('reversed', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('near_expiry_entry', 'reversed')
    op.drop_column('near_expiry_entry', 'unit_codes')
