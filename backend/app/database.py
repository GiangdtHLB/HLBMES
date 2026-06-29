"""Khởi tạo SQLAlchemy engine/session. ACID transaction cho dữ liệu nghiệp vụ
(tài liệu §8.1). Dùng session-per-request qua dependency get_db()."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_MAX_OVERFLOW, DB_POOL_SIZE, DATABASE_URL


def _engine_kwargs(url: str) -> dict:
    """Tham số engine theo loại CSDL.

    - SQLite (dev/test): check_same_thread=False cho uvicorn đa luồng.
    - Postgres / Microsoft SQL Server (prod): pool bền — pre_ping chống kết nối
      chết, recycle định kỳ, pool_size/overflow theo số worker.
    """
    kw: dict = {"future": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    else:
        kw["pool_pre_ping"] = True
        kw["pool_recycle"] = 1800
        kw["pool_size"] = DB_POOL_SIZE
        kw["max_overflow"] = DB_MAX_OVERFLOW
        # SQL Server (pyodbc): cô lập snapshot tốt hơn cho đọc đồng thời nếu DB bật READ_COMMITTED_SNAPSHOT.
    return kw


engine = create_engine(DATABASE_URL, **_engine_kwargs(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Base cho mọi ORM model."""


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(force: bool = False) -> None:
    """Tạo bảng nếu chưa có.

    SQLite (dev/test) luôn tự tạo cho tiện. Postgres / SQL Server CHỈ tạo khi
    MES_AUTO_CREATE=1 (hoặc force=True) — production dùng `alembic upgrade head`
    làm nguồn schema duy nhất, tránh lệch schema giữa create_all và migration.
    """
    from . import models  # noqa: F401  đảm bảo model đã được import/đăng ký
    from .config import AUTO_CREATE

    if force or AUTO_CREATE or DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
