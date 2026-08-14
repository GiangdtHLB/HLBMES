"""Vị trí cất Kho công ty (kho nguyên vật liệu): bảng material_location + material_lot.location_id

Revision ID: c3d4e5f6a7b1
Revises: 8b2c3d4e5f6a
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b1"
down_revision = "8b2c3d4e5f6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "material_location",
        sa.Column("loc_id", sa.Unicode(64), primary_key=True),
        sa.Column("code", sa.Unicode(64), nullable=False),
        sa.Column("name", sa.Unicode(255), nullable=False),
        sa.Column("zone", sa.Unicode(120), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_material_location_code", "material_location", ["code"], unique=True)

    with op.batch_alter_table("material_lot") as batch_op:
        batch_op.add_column(sa.Column("location_id", sa.Unicode(64), nullable=True))
        batch_op.create_foreign_key(
            "fk_material_lot_location_id", "material_location", ["location_id"], ["loc_id"]
        )
    op.create_index("ix_material_lot_location_id", "material_lot", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_material_lot_location_id", table_name="material_lot")
    with op.batch_alter_table("material_lot") as batch_op:
        batch_op.drop_constraint("fk_material_lot_location_id", type_="foreignkey")
        batch_op.drop_column("location_id")
    op.drop_index("ix_material_location_code", table_name="material_location")
    op.drop_table("material_location")
