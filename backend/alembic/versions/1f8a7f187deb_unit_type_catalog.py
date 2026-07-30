"""danh mục Loại đơn vị tồn kho (UnitTypeCatalog) — thay Vỉ/Keg hardcode bằng danh mục tự khai báo

Revision ID: 1f8a7f187deb
Revises: 9d2f6b8e1a4c
Create Date: 2026-07-29 09:00:00.000000

- unit_type_catalog: bảng mới (code/name/divide_by_pack_size/selectable/active) — mỗi loại
  khai báo cách quy đổi count->quantity (xem services/wms.py::_pack_divisor):
  divide_by_pack_size=True (giống Vỉ, nhân FinishedProduct.pack_size) hay False (giống Keg,
  1:1). Seed 3 dòng hệ thống bắt buộc phải có ngay sau migrate (không seed qua app/seed.py vì
  đây là dữ liệu cấu trúc lõi, không phải dữ liệu demo):
    - vi  (Vỉ)             divide_by_pack_size=True  selectable=True
    - keg (Keg)            divide_by_pack_size=False selectable=True
    - lon (Lon, phân rã)   divide_by_pack_size=False selectable=False (chỉ hệ thống tự sinh
      khi phân rã vỉ — xem services/wms.py::_decompose_one_vi — không cho chọn lúc khai báo SKU)
"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = '1f8a7f187deb'
down_revision = '9d2f6b8e1a4c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'unit_type_catalog',
        sa.Column('unit_type_id', sa.Unicode(64), primary_key=True),
        sa.Column('code', sa.Unicode(32), nullable=False),
        sa.Column('name', sa.Unicode(64), nullable=False),
        sa.Column('divide_by_pack_size', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('selectable', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_unit_type_catalog_code', 'unit_type_catalog', ['code'], unique=True)

    table = sa.table(
        'unit_type_catalog',
        sa.column('unit_type_id', sa.Unicode(64)),
        sa.column('code', sa.Unicode(32)),
        sa.column('name', sa.Unicode(64)),
        sa.column('divide_by_pack_size', sa.Boolean()),
        sa.column('selectable', sa.Boolean()),
        sa.column('active', sa.Boolean()),
    )
    op.bulk_insert(table, [
        {'unit_type_id': str(uuid.uuid4()), 'code': 'vi', 'name': 'Vỉ',
         'divide_by_pack_size': True, 'selectable': True, 'active': True},
        {'unit_type_id': str(uuid.uuid4()), 'code': 'keg', 'name': 'Keg',
         'divide_by_pack_size': False, 'selectable': True, 'active': True},
        {'unit_type_id': str(uuid.uuid4()), 'code': 'lon', 'name': 'Lon (phân rã)',
         'divide_by_pack_size': False, 'selectable': False, 'active': True},
    ])


def downgrade() -> None:
    op.drop_index('ix_unit_type_catalog_code', table_name='unit_type_catalog')
    op.drop_table('unit_type_catalog')
