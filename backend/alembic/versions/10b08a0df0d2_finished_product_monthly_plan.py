"""finished_product_monthly_plan table (Kế hoạch tiêu thụ tháng theo SKU)

Revision ID: 10b08a0df0d2
Revises: 10b08a0df0d1
Create Date: 2026-08-13

- finished_product_monthly_plan: mỗi (finished_product_id, year, month) có initial_qty (kế
  hoạch ban đầu) + adjusted_qty (kế hoạch điều chỉnh, tuỳ chọn) — thay cho cột
  finished_product.monthly_target_stock (đã bỏ ở migration a1b2c3d4e5f6).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "10b08a0df0d2"
down_revision = "10b08a0df0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "finished_product_monthly_plan",
        sa.Column("plan_id", sa.Unicode(64), primary_key=True),
        sa.Column("finished_product_id", sa.Unicode(64),
                  sa.ForeignKey("finished_product.finished_product_id"), nullable=False, index=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("initial_qty", sa.Float(), nullable=True),
        sa.Column("adjusted_qty", sa.Float(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_fp_monthly_plan", "finished_product_monthly_plan", ["finished_product_id", "year", "month"])


def downgrade():
    op.drop_constraint("uq_fp_monthly_plan", "finished_product_monthly_plan", type_="unique")
    op.drop_table("finished_product_monthly_plan")
