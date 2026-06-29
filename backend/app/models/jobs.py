"""Hàng đợi tác vụ nền (P2 — worker cho tác vụ AI/báo cáo dài).

Job lưu trong DB để trạng thái bền (sống qua restart tiến trình về mặt dữ liệu;
worker in-process chạy bằng ThreadPoolExecutor — quy mô lớn thay bằng Celery/RQ).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Integer, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class Job(Base):
    __tablename__ = "job"

    job_id: Mapped[str] = mapped_column(Unicode(64), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(Unicode(255), index=True)        # ai_report | recall | ...
    status: Mapped[str] = mapped_column(Unicode(255), default="queued", index=True)  # queued|running|done|error
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(UnicodeText, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)    # 0..100
    created_by: Mapped[Optional[str]] = mapped_column(Unicode(255), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
