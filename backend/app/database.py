"""Khởi tạo SQLAlchemy engine/session. ACID transaction cho dữ liệu nghiệp vụ
(tài liệu §8.1). Dùng session-per-request qua dependency get_db()."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL

# check_same_thread chỉ cần cho SQLite + uvicorn nhiều thread.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Base cho mọi ORM model."""


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Tạo bảng nếu chưa có. (Production nên dùng migration như Alembic.)"""
    from . import models  # noqa: F401  đảm bảo model đã được import/đăng ký

    Base.metadata.create_all(bind=engine)
