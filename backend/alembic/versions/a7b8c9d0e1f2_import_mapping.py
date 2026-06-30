"""import mapping explorer (integration_* tables)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-30

Tạo 5 bảng tầng integration cho Import Mapping Explorer. KHÔNG đụng bảng core.
Dùng Unicode/UnicodeText (NVARCHAR trên SQL Server) để giữ tiếng Việt.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'integration_mapping_profile',
        sa.Column('profile_id', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('target_table', sa.Unicode(length=64), nullable=False),
        sa.Column('source_system', sa.Unicode(length=64), nullable=True),
        sa.Column('source_type', sa.Unicode(length=32), nullable=False),
        sa.Column('key_field', sa.Unicode(length=64), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.Unicode(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('profile_id'),
    )
    op.create_index('ix_integration_mapping_profile_name', 'integration_mapping_profile', ['name'])
    op.create_index('ix_integration_mapping_profile_target_table', 'integration_mapping_profile', ['target_table'])

    op.create_table(
        'integration_column_mapping',
        sa.Column('mapping_id', sa.Unicode(length=64), nullable=False),
        sa.Column('profile_id', sa.Unicode(length=64), nullable=False),
        sa.Column('target_column', sa.Unicode(length=64), nullable=False),
        sa.Column('source_column', sa.Unicode(length=255), nullable=True),
        sa.Column('default_value', sa.UnicodeText(), nullable=True),
        sa.Column('transform_rule', sa.JSON(), nullable=True),
        sa.Column('validation_rule', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['profile_id'], ['integration_mapping_profile.profile_id']),
        sa.PrimaryKeyConstraint('mapping_id'),
    )
    op.create_index('ix_integration_column_mapping_profile_id', 'integration_column_mapping', ['profile_id'])

    op.create_table(
        'integration_import_file',
        sa.Column('file_id', sa.Unicode(length=64), nullable=False),
        sa.Column('filename', sa.Unicode(length=255), nullable=False),
        sa.Column('source_type', sa.Unicode(length=32), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('columns', sa.JSON(), nullable=False),
        sa.Column('sample', sa.JSON(), nullable=False),
        sa.Column('stored_path', sa.Unicode(length=512), nullable=True),
        sa.Column('uploaded_by', sa.Unicode(length=64), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('file_id'),
    )

    op.create_table(
        'integration_import_run',
        sa.Column('run_id', sa.Unicode(length=64), nullable=False),
        sa.Column('file_id', sa.Unicode(length=64), nullable=True),
        sa.Column('profile_id', sa.Unicode(length=64), nullable=True),
        sa.Column('source_system', sa.Unicode(length=64), nullable=True),
        sa.Column('target_table', sa.Unicode(length=64), nullable=False),
        sa.Column('key_field', sa.Unicode(length=64), nullable=False),
        sa.Column('status', sa.Unicode(length=32), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('inserted', sa.Integer(), nullable=False),
        sa.Column('updated', sa.Integer(), nullable=False),
        sa.Column('skipped', sa.Integer(), nullable=False),
        sa.Column('errored', sa.Integer(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('summary', sa.JSON(), nullable=True),
        sa.Column('run_by', sa.Unicode(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['file_id'], ['integration_import_file.file_id']),
        sa.PrimaryKeyConstraint('run_id'),
    )
    op.create_index('ix_integration_import_run_target_table', 'integration_import_run', ['target_table'])
    op.create_index('ix_integration_import_run_file_id', 'integration_import_run', ['file_id'])

    op.create_table(
        'integration_import_error',
        sa.Column('error_id', sa.Unicode(length=64), nullable=False),
        sa.Column('run_id', sa.Unicode(length=64), nullable=False),
        sa.Column('row_index', sa.Integer(), nullable=False),
        sa.Column('column', sa.Unicode(length=64), nullable=True),
        sa.Column('value', sa.UnicodeText(), nullable=True),
        sa.Column('message', sa.UnicodeText(), nullable=False),
        sa.Column('severity', sa.Unicode(length=16), nullable=False),
        sa.Column('raw_payload', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['integration_import_run.run_id']),
        sa.PrimaryKeyConstraint('error_id'),
    )
    op.create_index('ix_integration_import_error_run_id', 'integration_import_error', ['run_id'])


def downgrade() -> None:
    op.drop_table('integration_import_error')
    op.drop_table('integration_import_run')
    op.drop_table('integration_import_file')
    op.drop_table('integration_column_mapping')
    op.drop_table('integration_mapping_profile')
