"""Vi tri dich phieu dieu chuyen (WmsTransfer.to_location_id) tro thanh optional -- bo trong
nghia la don vi thanh "chua cat vi tri" (giong build_units khi khong chon vi tri), dung khi
nguoi dieu chuyen chua biet chinh xac o/ke luc lap phieu (VD xe chua toi noi). Xem
services/wms.py::create_transfer.

Revision ID: e5f6a7b8c9d3
Revises: d4e5f6a7b8c2
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d3"
down_revision = "d4e5f6a7b8c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("wms_transfer") as batch_op:
        batch_op.alter_column("to_location_id", existing_type=sa.Unicode(64), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("wms_transfer") as batch_op:
        batch_op.alter_column("to_location_id", existing_type=sa.Unicode(64), nullable=False)
