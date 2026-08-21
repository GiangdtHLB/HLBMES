"""merge workshop_location into material_location (scope column)

Revision ID: 7a22e8cdfb0a
Revises: d1b494a07a70
Create Date: 2026-08-21

Người dùng muốn 1 vị trí kho có thể đánh dấu dùng cho Kho công ty, Kho phân xưởng, hoặc CẢ HAI
(hiện ở cả 2 màn chọn vị trí) — thay vì 2 danh mục tách biệt (material_location/workshop_location)
như vừa dựng ở migration trước. Gộp lại 1 bảng duy nhất `material_location` + cột `scope`
("cong_ty" | "phan_xuong" | "ca_hai", mặc định "cong_ty" cho toàn bộ vị trí Kho công ty đã có
từ trước). `material_lot.workshop_location_id` và `transfer_kcpx_request.workshop_location_id`
đổi sang trỏ FK về `material_location.loc_id` thay vì `workshop_location.loc_id`. Bảng
`workshop_location` (mới tạo, chưa có dữ liệu thật ở thời điểm gộp) bị xoá sau khi copy dữ liệu
(nếu có) sang `material_location` với scope="phan_xuong".
"""
from alembic import op
import sqlalchemy as sa


revision = '7a22e8cdfb0a'
down_revision = 'd1b494a07a70'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('material_location') as batch_op:
        batch_op.add_column(sa.Column('scope', sa.Unicode(length=32), nullable=False, server_default='cong_ty'))

    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO material_location (loc_id, code, name, zone, active, scope) "
        "SELECT loc_id, code, name, zone, active, 'phan_xuong' FROM workshop_location"
    ))

    with op.batch_alter_table('material_lot') as batch_op:
        batch_op.drop_constraint('fk_material_lot_workshop_location_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_material_lot_workshop_location_id', 'material_location', ['workshop_location_id'], ['loc_id'])

    # transfer_kcpx_request.workshop_location_id: FK inline (không đặt tên) lúc tạo bảng — bảng
    # này vừa dựng cùng phiên làm việc, CHƯA có dữ liệu thật ở bất kỳ môi trường nào, nên xóa +
    # thêm lại cột (đơn giản, an toàn hơn dò tên constraint ẩn danh do SQLite tự sinh) thay vì
    # drop_constraint theo tên. Tách làm 2 batch riêng (drop rồi mới add) — gộp chung 1 batch
    # khiến SQLAlchemy phản chiếu (reflect) nhầm giữ lại CẢ FK cũ (workshop_location) lẫn FK mới
    # (material_location) trên cùng 1 cột trong bảng được recreate.
    with op.batch_alter_table('transfer_kcpx_request') as batch_op:
        batch_op.drop_column('workshop_location_id')
    with op.batch_alter_table('transfer_kcpx_request') as batch_op:
        batch_op.add_column(sa.Column('workshop_location_id', sa.Unicode(length=64),
                                      sa.ForeignKey('material_location.loc_id',
                                                   name='fk_transfer_kcpx_request_workshop_location_id'),
                                      nullable=True))

    op.drop_table('workshop_location')


def downgrade() -> None:
    op.create_table(
        'workshop_location',
        sa.Column('loc_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('zone', sa.Unicode(length=120), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('loc_id'),
    )
    op.create_index('ix_workshop_location_code', 'workshop_location', ['code'], unique=True)

    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO workshop_location (loc_id, code, name, zone, active) "
        "SELECT loc_id, code, name, zone, active FROM material_location WHERE scope = 'phan_xuong'"
    ))

    with op.batch_alter_table('material_lot') as batch_op:
        batch_op.drop_constraint('fk_material_lot_workshop_location_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_material_lot_workshop_location_id', 'workshop_location', ['workshop_location_id'], ['loc_id'])

    with op.batch_alter_table('transfer_kcpx_request') as batch_op:
        batch_op.drop_column('workshop_location_id')
    with op.batch_alter_table('transfer_kcpx_request') as batch_op:
        batch_op.add_column(sa.Column('workshop_location_id', sa.Unicode(length=64),
                                      sa.ForeignKey('workshop_location.loc_id',
                                                   name='fk_transfer_kcpx_request_workshop_location_id'),
                                      nullable=True))

    # Xoá SAU KHI đã đổi hướng FK ở material_lot/transfer_kcpx_request sang workshop_location —
    # tránh khoảng trống lúc các FK còn trỏ vào material_location trong khi dòng đã bị xoá.
    conn.execute(sa.text("DELETE FROM material_location WHERE scope = 'phan_xuong'"))

    with op.batch_alter_table('material_location') as batch_op:
        batch_op.drop_column('scope')
