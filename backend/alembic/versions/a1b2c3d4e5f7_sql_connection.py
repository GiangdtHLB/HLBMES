"""Khai báo kết nối CSDL SQL bên ngoài (Tích hợp)

Revision ID: a1b2c3d4e5f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-10

- sql_connection: khai báo host/port/database/username/password (thô, nội bộ) cho 1
  CSDL SQL bên ngoài đã mở port — bước đầu, chưa dùng làm nguồn import (xem services/
  integration_connection.py).
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sql_connection',
        sa.Column('connection_id', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('driver', sa.Unicode(length=64), nullable=False),
        sa.Column('host', sa.Unicode(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('database_name', sa.Unicode(length=255), nullable=False),
        sa.Column('username', sa.Unicode(length=255), nullable=False),
        sa.Column('password', sa.Unicode(length=255), nullable=True),
        sa.Column('extra_params', sa.Unicode(length=512), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_test_ok', sa.Boolean(), nullable=True),
        sa.Column('last_test_message', sa.Unicode(length=512), nullable=True),
        sa.PrimaryKeyConstraint('connection_id'),
    )


def downgrade() -> None:
    op.drop_table('sql_connection')
