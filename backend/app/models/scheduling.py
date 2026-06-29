"""Lập lịch sản xuất theo tài nguyên (tank lên men/line) + CIP + bảo trì.

ScheduleSlot = một khối thời gian chiếm dụng một tài nguyên: sản xuất (gắn work
order), CIP (vệ sinh giữa 2 mẻ trên cùng tank), hoặc bảo trì (khóa tài nguyên).
Bộ lập lịch (services/scheduler.py) sinh lại các slot production/cip; slot
maintenance giữ nguyên (nhập tay/từ kế hoạch bảo trì).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Text, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class ScheduleSlot(Base):
    __tablename__ = "schedule_slot"

    slot_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    resource: Mapped[str] = mapped_column(String(255), index=True)     # FV-01.. | Line-1.. | Nồi nấu
    kind: Mapped[str] = mapped_column(String(255), default="production")  # production | cip | maintenance
    wo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    wo_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(255), default="planned")   # planned | material_short
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
