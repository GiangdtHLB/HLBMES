"""OEE — danh mục lý do dừng máy theo dây chuyền (thay REASON_TREE hardcode) + RCFA/5Whys +
đếm dừng lắt nhắt theo tuần (MS&SL) — khớp đúng cấu trúc file OPI Excel gốc (8 nhóm tổn thất,
target %, phân tích nguyên nhân gốc, Pareto tuần).

Revision ID: 961553fef9f2
Revises: f86f0ee260fe
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa


revision = '961553fef9f2'
down_revision = 'f86f0ee260fe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oee_reason_catalog",
        sa.Column("reason_id", sa.Unicode(length=64), primary_key=True),
        sa.Column("line_code", sa.Unicode(length=64), nullable=True),
        sa.Column("category", sa.Unicode(length=64), nullable=False),
        sa.Column("sub_code", sa.Unicode(length=64), nullable=False),
        sa.Column("sub_label", sa.Unicode(length=255), nullable=False),
        sa.Column("machine_position", sa.Unicode(length=64), nullable=True),
        sa.Column("target_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("line_code", "category", "sub_code", name="uq_oee_reason_line_cat_sub"),
    )
    op.create_index("ix_oee_reason_catalog_line_code", "oee_reason_catalog", ["line_code"])
    op.create_index("ix_oee_reason_catalog_category", "oee_reason_catalog", ["category"])

    op.create_table(
        "oee_rcfa",
        sa.Column("rcfa_id", sa.Unicode(length=64), primary_key=True),
        sa.Column("rcfa_no", sa.Unicode(length=32), nullable=False),
        sa.Column("line_code", sa.Unicode(length=64), nullable=False),
        sa.Column("machine", sa.Unicode(length=255), nullable=False),
        sa.Column("part", sa.Unicode(length=255), nullable=True),
        sa.Column("stop_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_min", sa.Float(), nullable=False, server_default="0"),
        sa.Column("failure_function", sa.UnicodeText(), nullable=True),
        sa.Column("prior_signs", sa.UnicodeText(), nullable=True),
        sa.Column("technician", sa.Unicode(length=255), nullable=True),
        sa.Column("repair_min", sa.Float(), nullable=True),
        sa.Column("wait_min", sa.Float(), nullable=True),
        sa.Column("description", sa.UnicodeText(), nullable=True),
        sa.Column("replaced_parts", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("working_principle", sa.UnicodeText(), nullable=True),
        sa.Column("failure_mechanism", sa.UnicodeText(), nullable=True),
        sa.Column("analyst", sa.Unicode(length=255), nullable=True),
        sa.Column("factor", sa.Unicode(length=255), nullable=True),
        sa.Column("five_whys", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("category_4m1e", sa.Unicode(length=32), nullable=True),
        sa.Column("corrective_action", sa.UnicodeText(), nullable=True),
        sa.Column("preventive_action", sa.UnicodeText(), nullable=True),
        sa.Column("executor", sa.Unicode(length=255), nullable=True),
        sa.Column("complete_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checker", sa.Unicode(length=255), nullable=True),
        sa.Column("recheck_schedule", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_by", sa.Unicode(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rcfa_no", name="uq_oee_rcfa_no"),
    )
    op.create_index("ix_oee_rcfa_line_code", "oee_rcfa", ["line_code"])

    op.create_table(
        "oee_minor_stop_tally",
        sa.Column("tally_id", sa.Unicode(length=64), primary_key=True),
        sa.Column("reason_id", sa.Unicode(length=64), sa.ForeignKey("oee_reason_catalog.reason_id"), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("shift", sa.Unicode(length=16), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by", sa.Unicode(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reason_id", "iso_year", "iso_week", "shift", name="uq_oee_minor_stop_slot"),
    )
    op.create_index("ix_oee_minor_stop_tally_reason_id", "oee_minor_stop_tally", ["reason_id"])
    op.create_index("ix_oee_minor_stop_tally_iso_year", "oee_minor_stop_tally", ["iso_year"])

    op.add_column("downtime_event", sa.Column("reason_catalog_id", sa.Unicode(length=64), nullable=True))
    op.add_column("downtime_event", sa.Column("error_code", sa.Unicode(length=64), nullable=True))
    op.add_column("downtime_event", sa.Column("rcfa_id", sa.Unicode(length=64), nullable=True))
    op.add_column("downtime_event", sa.Column("repair_start_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("downtime_event", sa.Column("repair_end_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("downtime_event", sa.Column("repaired_by", sa.Unicode(length=255), nullable=True))
    op.add_column("downtime_event", sa.Column("corrective_action", sa.UnicodeText(), nullable=True))
    op.add_column("downtime_event", sa.Column("confirmations", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    with op.batch_alter_table("downtime_event") as batch_op:
        batch_op.create_foreign_key("fk_downtime_event_reason_catalog", "oee_reason_catalog",
                                     ["reason_catalog_id"], ["reason_id"])
        batch_op.create_foreign_key("fk_downtime_event_rcfa", "oee_rcfa", ["rcfa_id"], ["rcfa_id"])
    op.create_index("ix_downtime_event_reason_catalog_id", "downtime_event", ["reason_catalog_id"])
    op.create_index("ix_downtime_event_rcfa_id", "downtime_event", ["rcfa_id"])


def downgrade() -> None:
    op.drop_index("ix_downtime_event_rcfa_id", table_name="downtime_event")
    op.drop_index("ix_downtime_event_reason_catalog_id", table_name="downtime_event")
    with op.batch_alter_table("downtime_event") as batch_op:
        batch_op.drop_constraint("fk_downtime_event_rcfa", type_="foreignkey")
        batch_op.drop_constraint("fk_downtime_event_reason_catalog", type_="foreignkey")
    op.drop_column("downtime_event", "confirmations")
    op.drop_column("downtime_event", "corrective_action")
    op.drop_column("downtime_event", "repaired_by")
    op.drop_column("downtime_event", "repair_end_at")
    op.drop_column("downtime_event", "repair_start_at")
    op.drop_column("downtime_event", "rcfa_id")
    op.drop_column("downtime_event", "error_code")
    op.drop_column("downtime_event", "reason_catalog_id")

    op.drop_index("ix_oee_minor_stop_tally_iso_year", table_name="oee_minor_stop_tally")
    op.drop_index("ix_oee_minor_stop_tally_reason_id", table_name="oee_minor_stop_tally")
    op.drop_table("oee_minor_stop_tally")

    op.drop_index("ix_oee_rcfa_line_code", table_name="oee_rcfa")
    op.drop_table("oee_rcfa")

    op.drop_index("ix_oee_reason_catalog_category", table_name="oee_reason_catalog")
    op.drop_index("ix_oee_reason_catalog_line_code", table_name="oee_reason_catalog")
    op.drop_table("oee_reason_catalog")
