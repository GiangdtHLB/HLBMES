"""Cổng tích hợp: API key cho phần mềm ngoài + webhook đăng ký nhận sự kiện.

Tài liệu §9.3: hợp đồng API có version, idempotency, phân loại; §9.1: business
event bất biến cho consumer. Đây là nền tảng để kết nối ERP/WMS/BI và AI agent.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class ApiKey(Base):
    __tablename__ = "api_key"

    key_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Unicode(255))                  # tên hệ thống dùng key
    token: Mapped[str] = mapped_column(Unicode(128), unique=True, index=True)
    scopes: Mapped[str] = mapped_column(Unicode(255), default="read")  # "read" | "read,write"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, default=0)


class Webhook(Base):
    __tablename__ = "webhook"

    webhook_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    target_url: Mapped[str] = mapped_column(Unicode(512))
    event_types: Mapped[str] = mapped_column(Unicode(255), default="*")  # csv hoặc *
    secret: Mapped[Optional[str]] = mapped_column(Unicode(128), nullable=True)  # ký HMAC (mô phỏng)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)
