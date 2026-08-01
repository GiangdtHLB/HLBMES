"""near_expiry_entry: thêm finished_product_id + location_id (khai báo cận date trực tiếp
theo Sản phẩm + Vị trí, không còn tự nhận lô chiết theo ngày giờ — xem services/wms.py::
create_near_expiry_entry).

Revision ID: d2e3f4a5b6c8
Revises: b4c5d6e7f8b0
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e3f4a5b6c8"
down_revision = "b4c5d6e7f8b0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("near_expiry_entry", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("finished_product_id", sa.Unicode(64), nullable=True))
        batch_op.add_column(sa.Column("location_id", sa.Unicode(64), nullable=True))
        batch_op.create_index("ix_near_expiry_entry_finished_product_id", ["finished_product_id"])
        batch_op.create_index("ix_near_expiry_entry_location_id", ["location_id"])
        batch_op.create_foreign_key("fk_near_expiry_entry_finished_product_id", "finished_product",
                                     ["finished_product_id"], ["finished_product_id"])
        batch_op.create_foreign_key("fk_near_expiry_entry_location_id", "wms_location",
                                     ["location_id"], ["loc_id"])


def downgrade():
    with op.batch_alter_table("near_expiry_entry", recreate="auto") as batch_op:
        batch_op.drop_constraint("fk_near_expiry_entry_location_id", type_="foreignkey")
        batch_op.drop_constraint("fk_near_expiry_entry_finished_product_id", type_="foreignkey")
        batch_op.drop_index("ix_near_expiry_entry_location_id")
        batch_op.drop_index("ix_near_expiry_entry_finished_product_id")
        batch_op.drop_column("location_id")
        batch_op.drop_column("finished_product_id")
