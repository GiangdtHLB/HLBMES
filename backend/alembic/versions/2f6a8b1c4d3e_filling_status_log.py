"""filling_status_log (log tu dong trang thai may chiet 30K: 1=dang chiet, 2=dang CIP)

Revision ID: 2f6a8b1c4d3e
Revises: 9c1d4e7f2a5b
Create Date: 2026-11-13

Viet tay (khong autogenerate), mirror 48d7f493c7dd_brewhouse_step_log.py - xem
models/filling_log.py + services/filling_log.py. Yeu cau nguoi dung 2026-11-13: "may chay
running va (Trang nuoc nong hoac Duoi CO2 dang chay) thi la Dang CIP may, trang thai bang 2 ...
tren bieu do day chuyen 30k the hien nhu vay".
"""
from alembic import op
import sqlalchemy as sa

revision = "2f6a8b1c4d3e"
down_revision = "9c1d4e7f2a5b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filling_status_log",
        sa.Column("log_id", sa.Unicode(length=64), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("machine_running", sa.Boolean(), nullable=True),
        sa.Column("clean_flushing", sa.Boolean(), nullable=True),
        sa.Column("rins_return_gas_channel", sa.Boolean(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Float(), nullable=True),
        sa.Column("data_gap", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("log_id"),
    )
    op.create_index(op.f("ix_filling_status_log_status"), "filling_status_log", ["status"], unique=False)
    op.create_index(op.f("ix_filling_status_log_started_at"), "filling_status_log", ["started_at"], unique=False)
    op.create_index(op.f("ix_filling_status_log_ended_at"), "filling_status_log", ["ended_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_filling_status_log_ended_at"), table_name="filling_status_log")
    op.drop_index(op.f("ix_filling_status_log_started_at"), table_name="filling_status_log")
    op.drop_index(op.f("ix_filling_status_log_status"), table_name="filling_status_log")
    op.drop_table("filling_status_log")
