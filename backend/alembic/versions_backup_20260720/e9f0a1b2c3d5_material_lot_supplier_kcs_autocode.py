"""material_lot: nhà cung cấp + mã lô tự sinh theo năm + số lô KCS + đơn giá

Revision ID: e9f0a1b2c3d5
Revises: d8e9f0a1b2c4
Create Date: 2026-07-20

- Bảng supplier mới (Danh mục nhà cung cấp) + material_lot.supplier_id FK.
- material_lot.lot_year: năm nhập lô — mã lô (lot_code) từ nay do services/warehouse.py
  tự sinh tăng dần theo năm (VD 2026-00001), reset lại từ 1 mỗi năm mới, nên khóa duy
  nhất phải gồm cả lot_year, không chỉ lot_code (mirror BrewBatch.batch_year, xem
  a2b3c4d5e6f8_brew_batch_year_scoped_unique.py).
- material_lot.kcs_lot_no: số lô do bộ phận KCS tự điền khi khai báo chỉ tiêu chất lượng —
  khác với lot_code (mã lô do phần mềm tự sinh) và supplier_lot (số lô của nhà cung cấp).
- material_lot.unit_price: đơn giá nhập kho (màn hình Nhập kho mới).
- SQLite không cho DROP UNIQUE INDEX/constraint khai báo inline, phải tạo lại bảng.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e9f0a1b2c3d5'
down_revision = 'd8e9f0a1b2c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'supplier',
        sa.Column('supplier_id', sa.Unicode(length=64), nullable=False),
        sa.Column('code', sa.Unicode(length=64), nullable=False),
        sa.Column('name', sa.Unicode(length=255), nullable=False),
        sa.Column('address', sa.Unicode(length=255), nullable=True),
        sa.Column('contact', sa.Unicode(length=255), nullable=True),
        sa.Column('note', sa.Unicode(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('supplier_id'),
    )
    op.create_index(op.f('ix_supplier_code'), 'supplier', ['code'], unique=True)

    op.add_column('material_lot', sa.Column('lot_year', sa.Integer(), nullable=True))
    op.add_column('material_lot', sa.Column('supplier_id', sa.Unicode(length=64), nullable=True))
    op.add_column('material_lot', sa.Column('kcs_lot_no', sa.Unicode(length=64), nullable=True))
    op.add_column('material_lot', sa.Column('unit_price', sa.Float(), nullable=True))
    op.execute("""
        UPDATE material_lot SET lot_year = CAST(strftime('%Y', created_at) AS INTEGER)
    """)
    with op.batch_alter_table('material_lot', recreate='always') as batch_op:
        batch_op.alter_column('lot_year', nullable=False)
        batch_op.drop_index('ix_material_lot_lot_code')
        batch_op.create_index(op.f('ix_material_lot_lot_code'), ['lot_code'], unique=False)
        batch_op.create_index(op.f('ix_material_lot_lot_year'), ['lot_year'], unique=False)
        batch_op.create_unique_constraint('uq_material_lot_year_code', ['lot_year', 'lot_code'])
        batch_op.create_foreign_key('fk_material_lot_supplier_id', 'supplier', ['supplier_id'], ['supplier_id'])


def downgrade() -> None:
    with op.batch_alter_table('material_lot', recreate='always') as batch_op:
        batch_op.drop_constraint('fk_material_lot_supplier_id', type_='foreignkey')
        batch_op.drop_constraint('uq_material_lot_year_code', type_='unique')
        batch_op.drop_index(op.f('ix_material_lot_lot_year'))
        batch_op.drop_index(op.f('ix_material_lot_lot_code'))
        batch_op.create_index(op.f('ix_material_lot_lot_code'), ['lot_code'], unique=True)
        batch_op.drop_column('unit_price')
        batch_op.drop_column('kcs_lot_no')
        batch_op.drop_column('supplier_id')
        batch_op.drop_column('lot_year')
    op.drop_index(op.f('ix_supplier_code'), table_name='supplier')
    op.drop_table('supplier')
