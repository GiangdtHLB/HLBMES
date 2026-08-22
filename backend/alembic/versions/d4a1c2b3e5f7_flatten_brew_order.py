"""flatten brew_order (bỏ brew_master_order / lệnh nấu nhỏ)

Revision ID: d4a1c2b3e5f7
Revises: afe54be711b7
Create Date: 2026-08-21

Bỏ hẳn lớp "lệnh nấu lớn" (brew_master_order) — người dùng yêu cầu quay về mô hình PHẲNG: 1
brew_order = 1 dịch bia = đủ hành chính ngay trên chính dòng đó (mirror production_order),
không còn lồng "lệnh nấu nhỏ" bên trong. Đây gần như là đảo ngược đúng migration
c7d8e9f0a1b3 (migration đó đã chuyển issued_by/executor_unit/warehouse_keeper/reference_note/
start_date/end_date/safety_note TỪ brew_order SANG brew_master_order khi tạo ra lớp lồng này).

upgrade(): (1) thêm lại 7 cột hành chính vào brew_order; (2) copy dữ liệu từ brew_master_order
xuống các brew_order con của nó — con đầu tiên (seq nhỏ nhất) nhận order_code của master (số
lệnh thật, có ý nghĩa với người dùng); con thứ 2+ (chỉ 1 trường hợp thật trong dữ liệu hiện có)
nhận order_code = "{master_code}-{seq}", dò trùng rồi tăng hậu tố nếu đụng unique
(order_year, order_code); 9 brew_order "mồ côi" (master_order_id IS NULL, đã phẳng từ trước)
không đụng tới, giữ NULL ở 7 cột mới (đúng kỳ vọng — chưa từng có master để kế thừa); (3) drop
master_order_id/seq khỏi brew_order — `seq` được tạo với server_default='1' (migration
c7d8e9f0a1b3), MSSQL từ chối DROP COLUMN khi cột còn DEFAULT constraint tự sinh tên (DF__) nên
gọi prep_drop_columns trước (no-op trên SQLite, DEPLOY-CONTRACT §2B); (4) drop bảng
brew_master_order.

downgrade() CHỈ khôi phục SCHEMA (tạo lại bảng brew_master_order, thêm lại master_order_id=NULL/
seq=1 cho mọi dòng), KHÔNG phục dựng lại đúng nhóm cha/con gốc — sau khi order_code đã được hợp
nhất xuống các con, không còn đủ thông tin để tách ngược 100% chính xác về trạng thái trước khi
upgrade (mirror tinh thần "downgrade không đối xứng dữ liệu" của các migration lossy khác trong
repo, VD 7a22e8cdfb0a).
"""
from alembic import op
import sqlalchemy as sa

from app.alembic_mssql import prep_drop_columns


revision = 'd4a1c2b3e5f7'
down_revision = 'afe54be711b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brew_order', sa.Column('issued_by', sa.Unicode(length=255), nullable=True))
    op.add_column('brew_order', sa.Column('executor_unit', sa.Unicode(length=255), nullable=True))
    op.add_column('brew_order', sa.Column('warehouse_keeper', sa.Unicode(length=255), nullable=True))
    op.add_column('brew_order', sa.Column('reference_note', sa.UnicodeText(), nullable=True))
    op.add_column('brew_order', sa.Column('start_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('brew_order', sa.Column('end_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('brew_order', sa.Column('safety_note', sa.UnicodeText(), nullable=True))

    conn = op.get_bind()
    masters = conn.execute(sa.text(
        "SELECT brew_master_order_id, order_code, order_year, issued_by, executor_unit, "
        "warehouse_keeper, reference_note, start_date, end_date, safety_note FROM brew_master_order"
    )).mappings().all()
    for m in masters:
        children = conn.execute(sa.text(
            "SELECT brew_order_id, seq FROM brew_order WHERE master_order_id = :mid ORDER BY seq"
        ), {"mid": m["brew_master_order_id"]}).mappings().all()
        if not children:
            continue
        first_seq = children[0]["seq"]
        for child in children:
            code = m["order_code"] if child["seq"] == first_seq else f'{m["order_code"]}-{child["seq"]}'
            n = 2
            while conn.execute(sa.text(
                    "SELECT 1 FROM brew_order WHERE order_year = :y AND order_code = :c AND brew_order_id != :cid"
                ), {"y": m["order_year"], "c": code, "cid": child["brew_order_id"]}).first():
                code = f'{m["order_code"]}-{child["seq"]}-{n}'
                n += 1
            conn.execute(sa.text(
                "UPDATE brew_order SET order_code = :code, issued_by = :issued_by, "
                "executor_unit = :executor_unit, warehouse_keeper = :warehouse_keeper, "
                "reference_note = :reference_note, start_date = :start_date, end_date = :end_date, "
                "safety_note = :safety_note WHERE brew_order_id = :cid"
            ), {"code": code, "cid": child["brew_order_id"], "issued_by": m["issued_by"],
                "executor_unit": m["executor_unit"], "warehouse_keeper": m["warehouse_keeper"],
                "reference_note": m["reference_note"], "start_date": m["start_date"],
                "end_date": m["end_date"], "safety_note": m["safety_note"]})

    op.drop_index('ix_brew_order_master_order_id', table_name='brew_order')
    prep_drop_columns(conn, 'brew_order', ['seq', 'master_order_id'])
    op.drop_column('brew_order', 'seq')
    op.drop_column('brew_order', 'master_order_id')

    op.drop_index('ix_brew_master_order_order_code', table_name='brew_master_order')
    op.drop_table('brew_master_order')


def downgrade() -> None:
    op.create_table(
        'brew_master_order',
        sa.Column('brew_master_order_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('order_code', sa.Unicode(length=64), nullable=False),
        sa.Column('order_year', sa.Integer(), nullable=False),
        sa.Column('issued_by', sa.Unicode(length=255), nullable=True),
        sa.Column('executor_unit', sa.Unicode(length=255), nullable=True),
        sa.Column('warehouse_keeper', sa.Unicode(length=255), nullable=True),
        sa.Column('reference_note', sa.UnicodeText(), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('safety_note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('locked_by', sa.Unicode(length=255), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_brew_master_order_order_code', 'brew_master_order', ['order_code'], unique=True)

    op.add_column('brew_order', sa.Column('master_order_id', sa.Unicode(length=64), nullable=True))
    op.add_column('brew_order', sa.Column('seq', sa.Integer(), nullable=False, server_default='1'))
    op.create_index('ix_brew_order_master_order_id', 'brew_order', ['master_order_id'])

    op.drop_column('brew_order', 'safety_note')
    op.drop_column('brew_order', 'end_date')
    op.drop_column('brew_order', 'start_date')
    op.drop_column('brew_order', 'reference_note')
    op.drop_column('brew_order', 'warehouse_keeper')
    op.drop_column('brew_order', 'executor_unit')
    op.drop_column('brew_order', 'issued_by')
