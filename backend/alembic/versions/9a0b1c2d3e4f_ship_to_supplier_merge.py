"""Gộp ship_to_location vào supplier — Kho TP dùng chung 1 danh mục Nhà cung cấp làm nơi xuất đến

Revision ID: 9a0b1c2d3e4f
Revises: e11b49c4002d
Create Date: 2026-08-04

Theo yêu cầu người dùng 2026-08-04: "Bỏ danh mục nơi xuất đến ở kho thành phẩm, chỉ cần 1
danh mục nhà cung cấp là đủ. Chọn nơi xuất đến cũng từ nhà cung cấp này." — retire hẳn catalog
ship_to_location, dùng chung supplier cho cả nhà cung cấp NVL lẫn nơi xuất đến hàng thành phẩm.

Data migration: copy từng dòng ship_to_location sang supplier, GIỮ NGUYÊN đúng UUID
(supplier_id = ship_to_id cũ) — nhờ vậy 2 cột FK value hiện có (shipment.ship_to_id,
finished_goods_unit.ship_to_id) không cần đổi giá trị, chỉ cần đổi ĐÍCH của constraint. Nếu
code trùng với 1 supplier đã có sẵn (2 namespace trước đây độc lập), thêm hậu tố "-ST" (rồi
"-ST2", "-ST3"... nếu vẫn trùng) để không vỡ unique constraint. Trường "kind" (distributor/
retailer/export/other) không có chỗ tương ứng ở supplier — gộp vào "note" để không mất thông
tin. KHÔNG downgrade lại được (1 chiều, mirport formula.py migration).
"""
from alembic import op
import sqlalchemy as sa

revision = '9a0b1c2d3e4f'
down_revision = 'e11b49c4002d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    _migrate_ship_to_rows()
    _retarget_ship_to_fk('finished_goods_unit')
    _retarget_ship_to_fk('shipment')
    op.drop_index(op.f('ix_ship_to_location_code'), table_name='ship_to_location')
    op.drop_table('ship_to_location')


def _retarget_ship_to_fk(table: str) -> None:
    """Đổi đích FK ship_to_id từ ship_to_location -> supplier. Cột này được khai báo lúc tạo
    bảng qua ForeignKey INLINE (không đặt tên tường minh) — tên constraint thật sự do từng
    dialect tự sinh (MSSQL: FK__<hash>, không đoán trước được; SQLite: không có tên, và app
    không bật PRAGMA foreign_keys nên không enforce, xem database.py). Vì vậy KHÔNG đoán tên
    constraint mà tự dò bằng inspector/sys catalog trước khi drop (mirror app/alembic_mssql.py
    ::prep_drop_columns — cùng nguyên nhân: FK auto-name không đoán được)."""
    bind = op.get_bind()
    if bind.dialect.name == "mssql":
        for name in bind.execute(sa.text(f"""
                SELECT DISTINCT fk.name FROM sys.foreign_keys fk
                JOIN sys.foreign_key_columns k ON fk.object_id = k.constraint_object_id
                JOIN sys.columns c ON c.object_id = k.parent_object_id AND c.column_id = k.parent_column_id
                WHERE fk.parent_object_id = OBJECT_ID('{table}') AND c.name = 'ship_to_id'""")).scalars().all():
            bind.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT [{name}]"))
        bind.execute(sa.text(
            f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_ship_to_id_supplier "
            f"FOREIGN KEY (ship_to_id) REFERENCES supplier(supplier_id)"))
        return

    # sqlite/postgres: dò tên qua inspector — trên sqlite, FK không tên sẽ trả None (không
    # enforce nên bỏ qua an toàn); trên postgres, tên tồn tại và dò được bình thường.
    insp = sa.inspect(bind)
    old_name = next((fk["name"] for fk in insp.get_foreign_keys(table)
                     if "ship_to_id" in fk["constrained_columns"] and fk.get("name")), None)
    with op.batch_alter_table(table, recreate="auto") as batch_op:
        if old_name:
            batch_op.drop_constraint(old_name, type_="foreignkey")
        batch_op.create_foreign_key(f"fk_{table}_ship_to_id_supplier", "supplier",
                                    ["ship_to_id"], ["supplier_id"])


def _migrate_ship_to_rows() -> None:
    bind = op.get_bind()

    ship_to_t = sa.table(
        'ship_to_location', sa.column('ship_to_id', sa.Unicode(64)), sa.column('code', sa.Unicode(64)),
        sa.column('name', sa.Unicode(255)), sa.column('kind', sa.Unicode(255)),
        sa.column('address', sa.Unicode(255)), sa.column('contact', sa.Unicode(255)),
        sa.column('active', sa.Boolean()))
    supplier_t = sa.table(
        'supplier', sa.column('supplier_id', sa.Unicode(64)), sa.column('code', sa.Unicode(64)),
        sa.column('name', sa.Unicode(255)), sa.column('address', sa.Unicode(255)),
        sa.column('contact', sa.Unicode(255)), sa.column('note', sa.Unicode(255)),
        sa.column('active', sa.Boolean()))

    rows = bind.execute(sa.select(ship_to_t)).fetchall()
    if not rows:
        return
    existing_codes = {r.code for r in bind.execute(sa.select(supplier_t.c.code)).fetchall()}

    for r in rows:
        code = r.code
        suffix = 0
        while code in existing_codes:
            suffix += 1
            code = f"{r.code}-ST{suffix if suffix > 1 else ''}"
        existing_codes.add(code)
        note = f"Nơi xuất đến (loại: {r.kind})" if r.kind else "Nơi xuất đến"
        bind.execute(supplier_t.insert().values(
            supplier_id=r.ship_to_id, code=code, name=r.name, address=r.address,
            contact=r.contact, note=note, active=r.active))


def downgrade() -> None:
    raise RuntimeError("Không hỗ trợ downgrade — dữ liệu ship_to_location đã gộp vào supplier "
                       "(mirror formula.py migration).")
