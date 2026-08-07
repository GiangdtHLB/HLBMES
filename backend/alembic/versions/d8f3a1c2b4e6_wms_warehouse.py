"""Kho thành phẩm (WmsWarehouse) — cấp cha mới của WmsLocation

Revision ID: d8f3a1c2b4e6
Revises: d5d0e6365ad2
Create Date: 2026-08-07

- wms_warehouse: kho thành phẩm (VD "Kho Đông Mai", "Kho Hạ Long") — trước đây mỗi kho thực ra
  đang được khai báo trực tiếp thành 1 dòng WmsLocation phẳng (không có cấp cha), khiến không
  biết 1 lô đang ở KHO nào ngoài VỊ TRÍ nào. Thêm bảng này + wms_location.warehouse_id để tách
  2 cấp riêng (xem models/wms.py::WmsWarehouse/WmsLocation, services/wms.py).
- Data migration: mỗi WmsLocation hiện có được TỰ ĐỘNG nâng cấp thành 1 WmsWarehouse cùng
  mã/tên (không đổi mã/tên hiển thị cũ, không di chuyển FinishedGoodsUnit nào) — coi như đó vừa
  là kho vừa là vị trí mặc định của chính kho đó; người dùng khai báo thêm vị trí mới trong kho
  qua Danh mục Kho thành phẩm/Vị trí kho sau khi lên bản này.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8f3a1c2b4e6'
down_revision = 'd5d0e6365ad2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'wms_warehouse',
        sa.Column('warehouse_id', sa.Unicode(length=64), primary_key=True),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('address', sa.Unicode(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_wms_warehouse_code', 'wms_warehouse', ['code'], unique=True)

    # batch_alter_table: SQLite không hỗ trợ ALTER TABLE ADD COLUMN kèm FK constraint trực
    # tiếp (chỉ hỗ trợ qua copy-and-move) — batch mode xử lý việc này cho SQLite, và là no-op
    # (chạy ALTER thẳng) trên MSSQL/Postgres nên an toàn cho cả 2 engine.
    with op.batch_alter_table('wms_location') as batch_op:
        batch_op.add_column(sa.Column('warehouse_id', sa.Unicode(length=64), nullable=True))
        batch_op.create_foreign_key('fk_wms_location_warehouse_id', 'wms_warehouse',
                                     ['warehouse_id'], ['warehouse_id'])
    op.create_index('ix_wms_location_warehouse_id', 'wms_location', ['warehouse_id'])

    # Backfill: mỗi vị trí hiện có -> 1 kho mới cùng mã/tên, rồi tự trỏ về kho đó.
    bind = op.get_bind()
    locations = bind.execute(sa.text("SELECT loc_id, code, name FROM wms_location")).fetchall()
    for loc_id, code, name in locations:
        warehouse_id = f"WH-{loc_id}"
        bind.execute(sa.text(
            "INSERT INTO wms_warehouse (warehouse_id, code, name, address, active) "
            "VALUES (:wid, :code, :name, NULL, 1)"
        ), {"wid": warehouse_id, "code": code, "name": name})
        bind.execute(sa.text(
            "UPDATE wms_location SET warehouse_id = :wid WHERE loc_id = :lid"
        ), {"wid": warehouse_id, "lid": loc_id})


def downgrade():
    op.drop_index('ix_wms_location_warehouse_id', table_name='wms_location')
    with op.batch_alter_table('wms_location') as batch_op:
        batch_op.drop_constraint('fk_wms_location_warehouse_id', type_='foreignkey')
        batch_op.drop_column('warehouse_id')
    op.drop_index('ix_wms_warehouse_code', table_name='wms_warehouse')
    op.drop_table('wms_warehouse')
