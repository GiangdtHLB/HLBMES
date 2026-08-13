"""capa scope_type/scope_id + kcs_approval_note

Revision ID: 82986e9353e0
Revises: 6cd3fb3d3592
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "82986e9353e0"
down_revision = "6cd3fb3d3592"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("capa") as batch_op:
        batch_op.add_column(sa.Column("scope_type", sa.Unicode(255), nullable=True))
        batch_op.add_column(sa.Column("scope_id", sa.Unicode(64), nullable=True))
        batch_op.add_column(sa.Column("kcs_approval_note", sa.UnicodeText(), nullable=True))
    op.create_index("ix_capa_scope_id", "capa", ["scope_id"])


def downgrade():
    op.drop_index("ix_capa_scope_id", table_name="capa")
    with op.batch_alter_table("capa") as batch_op:
        batch_op.drop_column("kcs_approval_note")
        batch_op.drop_column("scope_id")
        batch_op.drop_column("scope_type")
