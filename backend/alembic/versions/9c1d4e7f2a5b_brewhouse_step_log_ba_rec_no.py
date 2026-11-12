"""brewhouse_step_log_ba_rec_no (them cot RecNo de biet Loai bia theo cong thuc Braumat)

Revision ID: 9c1d4e7f2a5b
Revises: 446d792c15d3
Create Date: 2026-11-11

Them cot ba_rec_no (BA_RecNo doc tu Brewhouse_Realtime, xem services/brewhouse_external.py::
BEER_TYPE_BY_RECNO) - yeu cau nguoi dung 2026-11-11: "ban can phai luu them Cot RecNo o tren sql
sever" de bao cao "Log he nau"/"Thoi gian ca me nau" loc/hien duoc cot Loai bia ma khong phai
parse JSON (start_snapshot/end_snapshot) moi lan truy van.
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns

revision = "9c1d4e7f2a5b"
down_revision = "446d792c15d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "brewhouse_step_log",
        sa.Column("ba_rec_no", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_brewhouse_step_log_ba_rec_no", "brewhouse_step_log", ["ba_rec_no"],
    )


def downgrade() -> None:
    op.drop_index("ix_brewhouse_step_log_ba_rec_no", table_name="brewhouse_step_log")
    # Cot nullable, khong co server_default -> khong sinh rang buoc DEFAULT dat ten tu dong tren
    # MSSQL (khac data_gap o 7b3c9e1f4a6d), nhung van goi prep_drop_columns cho dong nhat/an toan
    # neu sau nay co migration khac vo tinh them default (DEPLOY-CONTRACT Sec2(B)).
    prep_drop_columns(op.get_bind(), "brewhouse_step_log", ["ba_rec_no"])
    op.drop_column("brewhouse_step_log", "ba_rec_no")
