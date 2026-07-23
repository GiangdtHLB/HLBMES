"""Khai báo + test kết nối tới CSDL SQL bên ngoài (VD SQL Server đã mở port) — bước đầu
cho tích hợp dữ liệu sau này (chưa dùng làm nguồn cho Import Mapping Explorer). Hiện chỉ
hỗ trợ SQL Server qua pyodbc (đã có sẵn trong hệ thống, xem requirements.txt); các driver
khác (Postgres/MySQL) cần thêm dependency nên chưa hỗ trợ."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..common import new_id, utcnow
from ..errors import DomainError, NotFoundError
from ..models.integration import SqlConnection


@contextmanager
def safe_query(conn_name: str):
    """Bọc lỗi kết nối/truy vấn CSDL ngoài (login failed, timeout, mất mạng...) thành
    DomainError (400, JSON) thay vì để lộ ra 500 thô — vì các CSDL SCADA ngoài (energy,
    filling...) có thể lúc kết nối được lúc không (mạng WAN, login bị khoá tạm...), và một
    lỗi SQLAlchemy chưa bắt sẽ làm response không phải JSON, hỏng luôn phần xử lý lỗi ở
    frontend (vốn chỉ mong đợi JSON từ mọi status code)."""
    try:
        yield
    except SQLAlchemyError as e:
        raise DomainError(f"Không kết nối/truy vấn được CSDL \"{conn_name}\": {e}") from e


def _build_url(conn: SqlConnection) -> URL:
    query = {"driver": "ODBC Driver 18 for SQL Server"}
    if conn.extra_params:
        for part in conn.extra_params.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                query[k] = v
    return URL.create(
        "mssql+pyodbc", username=conn.username, password=conn.password,
        host=conn.host, port=conn.port, database=conn.database_name, query=query,
    )


def list_connections(db: Session) -> list[SqlConnection]:
    return db.execute(select(SqlConnection).order_by(SqlConnection.created_at.desc())).scalars().all()


def get_connection(db: Session, connection_id: str) -> SqlConnection:
    c = db.get(SqlConnection, connection_id)
    if not c:
        raise NotFoundError("Kết nối không tồn tại.")
    return c


def get_connection_by_purpose(db: Session, purpose: str) -> SqlConnection | None:
    """purpose lưu dạng CSV (VD "energy,filling_keg") vì 1 kết nối vật lý có thể được gán
    phục vụ nhiều báo cáo cùng lúc — so khớp theo từng token trong CSV, không so bằng chuỗi
    nguyên văn (nếu không sẽ không khớp khi CSV có nhiều hơn 1 mục đích)."""
    conns = db.execute(
        select(SqlConnection).where(SqlConnection.active == True)  # noqa: E712
        .order_by(SqlConnection.created_at.desc())
    ).scalars().all()
    for c in conns:
        if purpose in [p.strip() for p in (c.purpose or "").split(",") if p.strip()]:
            return c
    return None


def create_connection(db: Session, payload: dict, user) -> SqlConnection:
    c = SqlConnection(connection_id=new_id(), created_by=user.username,
                      created_at=utcnow(), updated_at=utcnow(), **payload)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def update_connection(db: Session, connection_id: str, payload: dict) -> SqlConnection:
    c = get_connection(db, connection_id)
    for key, value in payload.items():
        if key == "password" and not value:
            continue  # để trống khi sửa = giữ nguyên mật khẩu cũ
        setattr(c, key, value)
    c.updated_at = utcnow()
    db.commit()
    db.refresh(c)
    return c


def delete_connection(db: Session, connection_id: str) -> None:
    c = get_connection(db, connection_id)
    db.delete(c)
    db.commit()


def test_connection(db: Session, connection_id: str) -> dict:
    c = get_connection(db, connection_id)
    ok, message = _try_connect(c)
    c.last_tested_at = utcnow()
    c.last_test_ok = ok
    c.last_test_message = message[:500]
    db.commit()
    return {"ok": ok, "message": message}


def _try_connect(c: SqlConnection) -> tuple[bool, str]:
    engine = None
    try:
        engine = create_engine(_build_url(c), connect_args={"timeout": 5}, pool_pre_ping=False)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Kết nối thành công."
    except Exception as e:
        return False, str(e)
    finally:
        if engine is not None:
            engine.dispose()


def list_tables(db: Session, connection_id: str) -> dict:
    """Liệt kê tên bảng/view có trong CSDL — chỉ đọc, dùng reflection, để khám phá các
    bảng danh mục/lookup (VD ánh xạ ID hệ thống → tên) trước khi map dữ liệu thật."""
    c = get_connection(db, connection_id)
    engine = create_engine(_build_url(c), connect_args={"timeout": 8}, pool_pre_ping=False)
    try:
        with safe_query(c.name):
            inspector = inspect(engine)
            return {"tables": sorted(inspector.get_table_names()), "views": sorted(inspector.get_view_names())}
    finally:
        engine.dispose()


def preview_table(db: Session, connection_id: str, table_name: str, limit: int = 5) -> dict:
    """Xem trước cấu trúc (tên cột + kiểu) và vài dòng mẫu của 1 bảng/view qua kết nối đã
    khai báo — CHỈ ĐỌC (SELECT). Dùng reflection của SQLAlchemy (không nối chuỗi SQL thô
    với table_name người dùng nhập) để tránh SQL injection. Mục đích: xác định đúng tên
    cột thật của CSDL ngoài (VD SCADA/WinCC) trước khi map dữ liệu, tránh đoán mò."""
    c = get_connection(db, connection_id)
    engine = create_engine(_build_url(c), connect_args={"timeout": 8}, pool_pre_ping=False)
    try:
        with safe_query(c.name):
            inspector = inspect(engine)
            if table_name not in inspector.get_table_names() and table_name not in inspector.get_view_names():
                raise NotFoundError(f"Không tìm thấy bảng/view '{table_name}' trong CSDL.")
            columns = [{"name": col["name"], "type": str(col["type"])} for col in inspector.get_columns(table_name)]
            metadata = MetaData()
            tbl = Table(table_name, metadata, autoload_with=engine)
            with engine.connect() as conn:
                rows = conn.execute(select(tbl).limit(limit)).mappings().all()

            def _jsonable(v):
                if isinstance(v, Decimal):
                    return float(v)
                if hasattr(v, "isoformat"):
                    return v.isoformat()
                return v
            sample_rows = [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows]
            return {"table": table_name, "columns": columns, "sample_rows": sample_rows}
    finally:
        engine.dispose()


def to_out(c: SqlConnection) -> dict:
    """Serialize an toàn — KHÔNG bao giờ trả password thô, chỉ cờ password_set."""
    return {
        "connection_id": c.connection_id, "name": c.name, "driver": c.driver,
        "host": c.host, "port": c.port, "database_name": c.database_name,
        "username": c.username, "password_set": bool(c.password),
        "extra_params": c.extra_params, "purpose": c.purpose, "active": c.active,
        "created_by": c.created_by, "created_at": c.created_at, "updated_at": c.updated_at,
        "last_tested_at": c.last_tested_at, "last_test_ok": c.last_test_ok,
        "last_test_message": c.last_test_message,
    }
