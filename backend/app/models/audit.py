"""AuditLog — append-only (tài liệu §10.3).

Ghi: ai, khi nào, hành động, trước/sau, lý do, correlation_id. Bản ghi chỉ
được thêm, không sửa/xóa (thực thi ở tầng service, không cung cấp API update).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    audit_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    # seq gán tăng dần ở tầng service (DB-agnostic), dùng để sắp xếp ổn định.
    # unique=True: nếu có race tạo trùng seq → lỗi ngay (fail-loud), tránh hỏng âm thầm chuỗi hash.
    seq: Mapped[int] = mapped_column(Integer, index=True, unique=True, default=0)
    entity_type: Mapped[str] = mapped_column(String, index=True)
    entity_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String, default="system")
    actor_role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # Chuỗi hash tamper-evident: entry_hash = sha256(prev_hash + nội dung bản ghi).
    prev_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entry_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
