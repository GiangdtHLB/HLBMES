"""CAPA: duyệt 2 cấp (KCS -> Giám đốc SX-KT) + đính kèm tài liệu

Revision ID: 6cd3fb3d3592
Revises: a0613c8733c2
Create Date: 2026-08-12

- capa.kcs_approved_by/at, capa.director_approved_by/at: 2 bước duyệt tuần tự bắt buộc
  trước khi đóng CAPA (xem models/quality_ext.py::CAPA, services/quality_adv.py).
- capa_attachment (mới): metadata tài liệu đính kèm CAPA — file thật lưu trên đĩa
  (backend/uploads/capa/{capa_id}/...), bảng này không lưu blob.
"""
from alembic import op
import sqlalchemy as sa

revision = '6cd3fb3d3592'
down_revision = 'a0613c8733c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("capa", sa.Column("kcs_approved_by", sa.Unicode(255), nullable=True))
    op.add_column("capa", sa.Column("kcs_approved_at", sa.DateTime(), nullable=True))
    op.add_column("capa", sa.Column("director_approved_by", sa.Unicode(255), nullable=True))
    op.add_column("capa", sa.Column("director_approved_at", sa.DateTime(), nullable=True))

    op.create_table(
        "capa_attachment",
        sa.Column("attachment_id", sa.Unicode(64), primary_key=True),
        sa.Column("capa_id", sa.Unicode(64), sa.ForeignKey("capa.capa_id"), nullable=False),
        sa.Column("file_name", sa.Unicode(255), nullable=False),
        sa.Column("stored_path", sa.Unicode(500), nullable=False),
        sa.Column("note", sa.Unicode(255), nullable=True),
        sa.Column("uploaded_by", sa.Unicode(255), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_capa_attachment_capa_id", "capa_attachment", ["capa_id"])


def downgrade() -> None:
    op.drop_index("ix_capa_attachment_capa_id", table_name="capa_attachment")
    op.drop_table("capa_attachment")
    op.drop_column("capa", "director_approved_at")
    op.drop_column("capa", "director_approved_by")
    op.drop_column("capa", "kcs_approved_at")
    op.drop_column("capa", "kcs_approved_by")
