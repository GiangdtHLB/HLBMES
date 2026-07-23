"""dynamic custom fields (EAV) cho Import Mapping

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-06-30

Tầng custom field tách rời core: giữ cột ngoài schema mà KHÔNG ALTER bảng core.
- custom_field_definition: khai báo field động cho 1 bảng đích.
- custom_field_value: giá trị field động theo từng record (EAV).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'custom_field_definition',
        sa.Column('id', sa.Unicode(length=64), nullable=False),
        sa.Column('table_name', sa.Unicode(length=64), nullable=False),
        sa.Column('field_key', sa.Unicode(length=64), nullable=False),
        sa.Column('display_name', sa.Unicode(length=255), nullable=False),
        sa.Column('data_type', sa.Unicode(length=16), nullable=False),   # string|int|float|bool|date
        sa.Column('is_required', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('table_name', 'field_key', name='uq_custom_field_def'),
    )
    op.create_index('ix_custom_field_definition_table_name', 'custom_field_definition', ['table_name'])

    op.create_table(
        'custom_field_value',
        sa.Column('id', sa.Unicode(length=64), nullable=False),
        sa.Column('table_name', sa.Unicode(length=64), nullable=False),
        sa.Column('record_id', sa.Unicode(length=64), nullable=False),
        sa.Column('field_key', sa.Unicode(length=64), nullable=False),
        sa.Column('field_value', sa.UnicodeText(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('table_name', 'record_id', 'field_key', name='uq_custom_field_value'),
    )
    op.create_index('ix_custom_field_value_rec', 'custom_field_value', ['table_name', 'record_id'])


def downgrade() -> None:
    op.drop_table('custom_field_value')
    op.drop_table('custom_field_definition')
