"""tách đề nghị nhận kho thành phiếu (header) + nhiều dòng vật tư (line)

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-08

1 phiếu đề nghị nhận kho có thể gồm nhiều vật tư khác nhau — tách material_id/
quantity/uom/preferred_lot_id/status/fulfilled_*/reason từ material_request
(trước đây 1 dòng = 1 phiếu) sang bảng con material_request_line mới (1 phiếu
= nhiều dòng, mỗi dòng xử lý duyệt/từ chối độc lập vì mỗi vật tư cần chọn lô riêng).
"""
from alembic import op
import sqlalchemy as sa

revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'material_request_line',
        sa.Column('line_id', sa.Unicode(length=64), nullable=False),
        sa.Column('request_id', sa.Unicode(length=64), sa.ForeignKey('material_request.request_id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('material_id', sa.Unicode(length=64), sa.ForeignKey('material.material_id'), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('uom', sa.Unicode(length=255), nullable=False, server_default='kg'),
        sa.Column('preferred_lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=True),
        sa.Column('status', sa.Unicode(length=255), nullable=False, server_default='pending'),
        sa.Column('fulfilled_lot_id', sa.Unicode(length=64), sa.ForeignKey('material_lot.lot_id'), nullable=True),
        sa.Column('fulfilled_qty', sa.Float(), nullable=True),
        sa.Column('fulfilled_by', sa.Unicode(length=255), nullable=True),
        sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.UnicodeText(), nullable=True),
        sa.PrimaryKeyConstraint('line_id'),
    )
    op.create_index('ix_material_request_line_request_id', 'material_request_line', ['request_id'])
    op.create_index('ix_material_request_line_material_id', 'material_request_line', ['material_id'])
    op.create_index('ix_material_request_line_status', 'material_request_line', ['status'])

    # Chuyển dữ liệu cũ (1 dòng = 1 phiếu) thành 1 dòng con của chính phiếu đó,
    # rồi bỏ các cột dòng-cụ-thể khỏi header (môi trường dev, chưa có dữ liệu thật cần giữ nguyên).
    conn = op.get_bind()
    # Sinh id ngẫu nhiên theo từng dialect (randomblob chỉ có ở SQLite; MSSQL dùng NEWID()).
    _d = conn.dialect.name
    _idexpr = {
        "sqlite": "lower(hex(randomblob(16)))",
        "postgresql": "replace(cast(gen_random_uuid() as text), '-', '')",
    }.get(_d, "lower(replace(convert(varchar(36), newid()), '-', ''))")  # mssql & mặc định
    conn.execute(sa.text(f"""
        INSERT INTO material_request_line
            (line_id, request_id, seq, material_id, quantity, uom, preferred_lot_id,
             status, fulfilled_lot_id, fulfilled_qty, fulfilled_by, fulfilled_at, reason)
        SELECT {_idexpr}, request_id, 0, material_id, quantity, uom, preferred_lot_id,
               status, fulfilled_lot_id, fulfilled_qty, fulfilled_by, fulfilled_at, reason
        FROM material_request
    """))

    # MSSQL: DROP COLUMN chặn nếu cột còn FK / DEFAULT phụ thuộc (SQLite recreate tự lo).
    # Drop FK + DEFAULT constraint trên các cột sắp bỏ trước khi drop_column.
    if _d == "mssql":
        _dropcols = ("material_id", "quantity", "uom", "preferred_lot_id", "status",
                     "fulfilled_lot_id", "fulfilled_qty", "fulfilled_by", "fulfilled_at", "reason")
        _in = ",".join(f"'{c}'" for c in _dropcols)
        for _fk in conn.execute(sa.text(
                "SELECT name FROM sys.foreign_keys WHERE parent_object_id = OBJECT_ID('material_request')")).scalars().all():
            conn.execute(sa.text(f"ALTER TABLE material_request DROP CONSTRAINT [{_fk}]"))
        for _dc in conn.execute(sa.text(f"""
                SELECT dc.name FROM sys.default_constraints dc
                JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
                WHERE dc.parent_object_id = OBJECT_ID('material_request') AND c.name IN ({_in})""")).scalars().all():
            conn.execute(sa.text(f"ALTER TABLE material_request DROP CONSTRAINT [{_dc}]"))

    with op.batch_alter_table('material_request') as batch:
        batch.drop_index('ix_material_request_material_id')
        batch.drop_index('ix_material_request_status')
        batch.drop_column('material_id')
        batch.drop_column('quantity')
        batch.drop_column('uom')
        batch.drop_column('preferred_lot_id')
        batch.drop_column('status')
        batch.drop_column('fulfilled_lot_id')
        batch.drop_column('fulfilled_qty')
        batch.drop_column('fulfilled_by')
        batch.drop_column('fulfilled_at')
        batch.drop_column('reason')


def downgrade() -> None:
    with op.batch_alter_table('material_request') as batch:
        batch.add_column(sa.Column('material_id', sa.Unicode(length=64), nullable=True))
        batch.add_column(sa.Column('quantity', sa.Float(), nullable=True))
        batch.add_column(sa.Column('uom', sa.Unicode(length=255), nullable=True))
        batch.add_column(sa.Column('preferred_lot_id', sa.Unicode(length=64), nullable=True))
        batch.add_column(sa.Column('status', sa.Unicode(length=255), nullable=True))
        batch.add_column(sa.Column('fulfilled_lot_id', sa.Unicode(length=64), nullable=True))
        batch.add_column(sa.Column('fulfilled_qty', sa.Float(), nullable=True))
        batch.add_column(sa.Column('fulfilled_by', sa.Unicode(length=255), nullable=True))
        batch.add_column(sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('reason', sa.UnicodeText(), nullable=True))
        batch.create_index('ix_material_request_material_id', ['material_id'])
        batch.create_index('ix_material_request_status', ['status'])
    op.drop_table('material_request_line')
