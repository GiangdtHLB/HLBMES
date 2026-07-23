"""Helper dùng chung trong các file migration (backend/alembic/versions/*.py) để
chạy sạch trên MSSQL (SQL Server) — KHÔNG đặt trong alembic/versions/ vì Alembic
quét mọi *.py trong đó như 1 migration script (cần biến `revision`)."""
import sqlalchemy as sa


def prep_drop_columns(conn, table, cols):
    """MSSQL: gỡ FK + DEFAULT constraint (tên tự sinh FK__/DF__) đang ràng buộc
    lên `cols` trước khi drop_column — MSSQL từ chối DROP COLUMN nếu cột còn bị
    một constraint tự sinh tên tham chiếu tới. No-op trên sqlite/postgres (batch
    recreate hoặc DROP COLUMN native của 2 dialect này tự lo việc này)."""
    if conn.dialect.name != "mssql":
        return
    inlist = ",".join(f"'{c}'" for c in cols)
    for name in conn.execute(sa.text(f"""
            SELECT DISTINCT fk.name FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns k ON fk.object_id = k.constraint_object_id
            JOIN sys.columns c ON c.object_id = k.parent_object_id AND c.column_id = k.parent_column_id
            WHERE fk.parent_object_id = OBJECT_ID('{table}') AND c.name IN ({inlist})""")).scalars().all():
        conn.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT [{name}]"))
    for name in conn.execute(sa.text(f"""
            SELECT dc.name FROM sys.default_constraints dc
            JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
            WHERE dc.parent_object_id = OBJECT_ID('{table}') AND c.name IN ({inlist})""")).scalars().all():
        conn.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT [{name}]"))
