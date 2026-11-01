"""brewhouse_step_log (log tu dong tung buoc he nau theo oder/batch/year)

Revision ID: 48d7f493c7dd
Revises: 015a8fcbb6a0
Create Date: 2026-11-01

Viet tay (khong autogenerate) vi mes.db dev cuc bo dang co 1 FK tham chieu bang da bi xoa
("wms_warehouse") lam alembic revision --autogenerate loi khi phan anh (reflect) CSDL hien tai
- khong lien quan toi bang moi nay. Xem models/brewhouse_log.py + services/brewhouse_log.py.
"""
from alembic import op
import sqlalchemy as sa

revision = "48d7f493c7dd"
down_revision = "015a8fcbb6a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brewhouse_step_log",
        sa.Column("log_id", sa.Unicode(length=64), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=False),
        sa.Column("equipment_name", sa.Unicode(length=255), nullable=False),
        sa.Column("ba_year", sa.Integer(), nullable=True),
        sa.Column("ba_order_no", sa.Unicode(length=64), nullable=True),
        sa.Column("ba_batch_no", sa.Unicode(length=64), nullable=True),
        sa.Column("step_no", sa.Integer(), nullable=True),
        sa.Column("step_name", sa.Unicode(length=255), nullable=True),
        sa.Column("eop_state_label", sa.Unicode(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Float(), nullable=True),
        sa.Column("step_minutes_setpoint", sa.Float(), nullable=True),
        sa.Column("start_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("end_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("log_id"),
    )
    op.create_index(op.f("ix_brewhouse_step_log_equipment_id"), "brewhouse_step_log", ["equipment_id"], unique=False)
    op.create_index(op.f("ix_brewhouse_step_log_ba_year"), "brewhouse_step_log", ["ba_year"], unique=False)
    op.create_index(op.f("ix_brewhouse_step_log_ba_order_no"), "brewhouse_step_log", ["ba_order_no"], unique=False)
    op.create_index(op.f("ix_brewhouse_step_log_ba_batch_no"), "brewhouse_step_log", ["ba_batch_no"], unique=False)
    op.create_index(op.f("ix_brewhouse_step_log_started_at"), "brewhouse_step_log", ["started_at"], unique=False)
    op.create_index(op.f("ix_brewhouse_step_log_ended_at"), "brewhouse_step_log", ["ended_at"], unique=False)
    op.create_index(
        "ix_brewhouse_step_log_batch", "brewhouse_step_log",
        ["ba_year", "ba_order_no", "ba_batch_no", "equipment_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_brewhouse_step_log_batch", table_name="brewhouse_step_log")
    op.drop_index(op.f("ix_brewhouse_step_log_ended_at"), table_name="brewhouse_step_log")
    op.drop_index(op.f("ix_brewhouse_step_log_started_at"), table_name="brewhouse_step_log")
    op.drop_index(op.f("ix_brewhouse_step_log_ba_batch_no"), table_name="brewhouse_step_log")
    op.drop_index(op.f("ix_brewhouse_step_log_ba_order_no"), table_name="brewhouse_step_log")
    op.drop_index(op.f("ix_brewhouse_step_log_ba_year"), table_name="brewhouse_step_log")
    op.drop_index(op.f("ix_brewhouse_step_log_equipment_id"), table_name="brewhouse_step_log")
    op.drop_table("brewhouse_step_log")
