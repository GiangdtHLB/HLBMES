"""drop_production_order

Revision ID: 54e88b2beb92
Revises: 36f5abb78e7e
Create Date: 2026-08-29 00:00:00.000000

Xóa hẳn "Lệnh sản xuất (ERP)" (ProductionOrder) — Mẻ sản xuất (BatchExecution) và Work Order
giờ trỏ THẲNG vào Lệnh nấu (BrewOrder), bỏ hẳn lớp gián tiếp qua ProductionOrder. Xem plan
"Xóa hẳn Lệnh sản xuất (ERP)" — không còn dữ liệu mẻ/EBR thật nào phụ thuộc ProductionOrder
trên server thật (xác nhận với người dùng trước khi làm), migration này chỉ cần xử lý đúng dữ
liệu DEV/demo hiện có để test suite không vỡ.

Backfill (theo thứ tự): với mỗi ProductionOrder đã có sẵn 1 BrewOrder trỏ tới
(brew_order.production_order_id), map production_order_id -> brew_order_id đó. Với
ProductionOrder MỒ CÔI (không BrewOrder nào trỏ tới) nhưng vẫn được batch_execution/brew_record/
work_order tham chiếu, tự tạo 1 BrewOrder "bóng ngược" copy y hệt order_code (giữ nguyên chuỗi,
dedup nếu trùng — quan trọng để order_code hiển thị/hash trong EBR không đổi) + product_id/
recipe_version_id/planned_qty, rồi thêm vào map. Sau đó update batch_execution.order_id/
work_order.brew_order_id/brew_record.brew_order_id theo map, mới xóa cột/bảng ProductionOrder.
"""
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '54e88b2beb92'
down_revision = '36f5abb78e7e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('work_order', sa.Column('brew_order_id', sa.Unicode(length=64), nullable=True))
    conn = op.get_bind()

    # 1) ProductionOrder đã có sẵn 1 BrewOrder con — map thẳng.
    mapping: dict[str, str] = {
        row["production_order_id"]: row["brew_order_id"]
        for row in conn.execute(sa.text(
            "SELECT production_order_id, brew_order_id FROM brew_order WHERE production_order_id IS NOT NULL"
        )).mappings().all()
    }

    # 2) ProductionOrder mồ côi (không BrewOrder nào trỏ tới) nhưng vẫn bị batch_execution/
    # brew_record/work_order tham chiếu — tự tạo 1 BrewOrder "bóng ngược" cho từng dòng.
    orphan_pos = conn.execute(sa.text(
        "SELECT DISTINCT po.order_id, po.order_code, po.product_id, po.recipe_version_id, "
        "       po.planned_qty, po.created_by, po.created_at "
        "FROM production_order po "
        "WHERE po.order_id NOT IN (SELECT production_order_id FROM brew_order WHERE production_order_id IS NOT NULL) "
        "AND ("
        "  EXISTS (SELECT 1 FROM batch_execution be WHERE be.order_id = po.order_id)"
        "  OR EXISTS (SELECT 1 FROM brew_record br WHERE br.production_order_id = po.order_id)"
        "  OR EXISTS (SELECT 1 FROM work_order wo WHERE wo.production_order_id = po.order_id)"
        ")"
    )).mappings().all()
    for po in orphan_pos:
        code = po["order_code"]
        n = 2
        while conn.execute(sa.text("SELECT 1 FROM brew_order WHERE order_code = :c"), {"c": code}).first():
            code = f'{po["order_code"]}-{n}'
            n += 1
        created_at = po["created_at"] or datetime.now(timezone.utc)
        order_year = created_at.year if hasattr(created_at, "year") else datetime.now(timezone.utc).year
        new_brew_order_id = str(uuid.uuid4())
        conn.execute(sa.text(
            "INSERT INTO brew_order (brew_order_id, order_code, order_year, product_id, "
            "  recipe_version_id, planned_batch_count, planned_volume_hl, volume_tolerance_hl, "
            "  created_by, created_at, locked) "
            "VALUES (:id, :code, :year, :product_id, :rv_id, 1, :planned_qty, 0.0, :created_by, :created_at, 0)"
        ), {"id": new_brew_order_id, "code": code, "year": order_year, "product_id": po["product_id"],
            "rv_id": po["recipe_version_id"], "planned_qty": po["planned_qty"] or 0.0,
            "created_by": po["created_by"], "created_at": created_at})
        mapping[po["order_id"]] = new_brew_order_id

    # 3) Cập nhật mọi tham chiếu theo map vừa dựng.
    for old_id, new_id in mapping.items():
        conn.execute(sa.text("UPDATE batch_execution SET order_id = :new WHERE order_id = :old"),
                    {"new": new_id, "old": old_id})
        conn.execute(sa.text("UPDATE work_order SET brew_order_id = :new WHERE production_order_id = :old"),
                    {"new": new_id, "old": old_id})
        conn.execute(sa.text(
            "UPDATE brew_record SET brew_order_id = :new "
            "WHERE production_order_id = :old AND brew_order_id IS NULL"
        ), {"new": new_id, "old": old_id})

    op.drop_index('ix_work_order_production_order_id', table_name='work_order')
    with op.batch_alter_table('work_order', recreate='always') as batch_op:
        batch_op.alter_column('brew_order_id', existing_type=sa.Unicode(length=64), nullable=False)
        batch_op.drop_column('production_order_id')
    op.create_index('ix_work_order_brew_order_id', 'work_order', ['brew_order_id'])

    # batch_execution.order_id giữ nguyên cột/index — chỉ đổi Ý NGHĨA giá trị (đã UPDATE ở trên)
    # + gỡ FK vật lý cũ trỏ production_order (bảng sắp xóa). FK này tạo từ lúc init_schema nên
    # không tên (name=None khi reflect) — phải gán tên qua naming_convention để drop_constraint
    # nhận diện được trên SQLite (mirror batch mode drop unnamed FK, xem alembic batch docs).
    _naming = {'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'}
    with op.batch_alter_table('batch_execution', recreate='always', naming_convention=_naming) as batch_op:
        batch_op.drop_constraint('fk_batch_execution_order_id_production_order', type_='foreignkey')

    op.drop_index('ix_brew_order_production_order_id', table_name='brew_order')
    op.drop_column('brew_order', 'production_order_id')

    # brew_record.brew_order_id GIỮ NGUYÊN nullable (khác work_order — không siết NOT NULL): vẫn
    # có dữ liệu demo/dashboard tạo BrewRecord thẳng bằng ORM không qua Lệnh nấu nào (seed.py::
    # _seed_brewing) — chỉ tầng service (create_brew_record) bắt buộc chọn Lệnh nấu, không phải
    # ràng buộc DB.
    op.drop_index('ix_brew_record_production_order_id', table_name='brew_record')
    op.drop_column('brew_record', 'production_order_id')

    op.drop_table('production_order_material_line')
    op.drop_table('production_order')


def downgrade() -> None:
    op.create_table(
        'production_order',
        sa.Column('order_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('order_code', sa.Unicode(length=64), unique=True, index=True),
        sa.Column('beer_type_id', sa.Unicode(length=64), index=True),
        sa.Column('product_id', sa.Unicode(length=64), nullable=True),
        sa.Column('planned_qty', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False),
        sa.Column('due_time', sa.DateTime(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('status', sa.Unicode(length=255), nullable=False),
        sa.Column('source_version', sa.Unicode(length=255), nullable=True),
        sa.Column('recipe_version_id', sa.Unicode(length=64), nullable=True, index=True),
        sa.Column('planned_batch_count', sa.Integer(), nullable=True),
        sa.Column('issued_by', sa.Unicode(length=255), nullable=True),
        sa.Column('executor_unit', sa.Unicode(length=255), nullable=True),
        sa.Column('warehouse_keeper', sa.Unicode(length=255), nullable=True),
        sa.Column('reference_note', sa.UnicodeText(), nullable=True),
        sa.Column('start_date', sa.DateTime(), nullable=True),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('safety_note', sa.UnicodeText(), nullable=True),
        sa.Column('created_by', sa.Unicode(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'production_order_material_line',
        sa.Column('line_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('order_id', sa.Unicode(length=64), index=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('stt_label', sa.Unicode(length=16), nullable=True),
        sa.Column('is_header', sa.Boolean(), nullable=False),
        sa.Column('material_id', sa.Unicode(length=64), nullable=True),
        sa.Column('material_name', sa.Unicode(length=255), nullable=True),
        sa.Column('material_group_code', sa.Unicode(length=64), nullable=True),
        sa.Column('member_qty_snapshot', sa.JSON(), nullable=True),
        sa.Column('uom', sa.Unicode(length=64), nullable=True),
        sa.Column('qty_per_batch', sa.Float(), nullable=True),
        sa.Column('qty_total', sa.Float(), nullable=True),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('stock_company_snapshot', sa.Float(), nullable=True),
        sa.Column('stock_workshop_snapshot', sa.Float(), nullable=True),
        sa.Column('qty_from_company', sa.Float(), nullable=True),
        sa.Column('qty_from_workshop', sa.Float(), nullable=True),
    )

    op.add_column('brew_record', sa.Column('production_order_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_brew_record_production_order_id', 'brew_record', ['production_order_id'])

    op.add_column('brew_order', sa.Column('production_order_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_brew_order_production_order_id', 'brew_order', ['production_order_id'])

    op.drop_index('ix_work_order_brew_order_id', table_name='work_order')
    op.add_column('work_order', sa.Column('production_order_id', sa.Unicode(length=64), nullable=True))
    op.create_index('ix_work_order_production_order_id', 'work_order', ['production_order_id'])
    with op.batch_alter_table('work_order') as batch_op:
        batch_op.alter_column('brew_order_id', existing_type=sa.Unicode(length=64), nullable=True)
    op.drop_column('work_order', 'brew_order_id')
