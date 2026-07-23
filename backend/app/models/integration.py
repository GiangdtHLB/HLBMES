"""Cổng tích hợp: API key cho phần mềm ngoài + webhook đăng ký nhận sự kiện.

Tài liệu §9.3: hợp đồng API có version, idempotency, phân loại; §9.1: business
event bất biến cho consumer. Đây là nền tảng để kết nối ERP/WMS/BI và AI agent.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Integer, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import UTCDateTime, new_id, utcnow
from ..database import Base


class ApiKey(Base):
    __tablename__ = "api_key"

    key_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Unicode(255))                  # tên hệ thống dùng key
    token: Mapped[str] = mapped_column(Unicode(128), unique=True, index=True)
    scopes: Mapped[str] = mapped_column(Unicode(255), default="read")  # "read" | "read,write"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, default=0)


class Webhook(Base):
    __tablename__ = "webhook"

    webhook_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    target_url: Mapped[str] = mapped_column(Unicode(512))
    event_types: Mapped[str] = mapped_column(Unicode(255), default="*")  # csv hoặc *
    secret: Mapped[Optional[str]] = mapped_column(Unicode(128), nullable=True)  # ký HMAC (mô phỏng)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)


class SqlConnection(Base):
    """Khai báo kết nối tới 1 CSDL SQL bên ngoài (đã mở port) — bước đầu để sau này dùng
    làm nguồn dữ liệu tích hợp (VD nạp vào Import Mapping Explorer). Hiện chỉ hỗ trợ
    SQL Server (driver='mssql', qua pyodbc đã có sẵn trong hệ thống — xem services/
    integration_connection.py). Mật khẩu lưu thô (hệ thống nội bộ, on-prem) — API
    KHÔNG BAO GIỜ trả lại giá trị mật khẩu, chỉ trả cờ password_set."""
    __tablename__ = "sql_connection"

    connection_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Unicode(255))
    driver: Mapped[str] = mapped_column(Unicode(64), default="mssql")
    host: Mapped[str] = mapped_column(Unicode(255))
    port: Mapped[int] = mapped_column(Integer, default=1433)
    database_name: Mapped[str] = mapped_column(Unicode(255))
    username: Mapped[str] = mapped_column(Unicode(255))
    password: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    extra_params: Mapped[Optional[str]] = mapped_column(Unicode(512), nullable=True)  # VD "Encrypt=yes&TrustServerCertificate=yes"
    # Module MES được chỉ định dùng kết nối này (VD "energy") — chỉ là gán/khai báo, CHƯA
    # thật sự truy vấn dữ liệu (đợi người dùng cung cấp bảng/query cụ thể cho từng module).
    purpose: Mapped[Optional[str]] = mapped_column(Unicode(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    last_test_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[Optional[str]] = mapped_column(Unicode(512), nullable=True)
