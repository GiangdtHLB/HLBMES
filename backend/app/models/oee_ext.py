"""Sự kiện dừng máy (downtime) cho reason-tree + Pareto + MTBF/MTTR (§7.7).

Cây lý do (reason-tree) là hằng số trong services/downtime.py (REASON_TREE);
mỗi sự kiện gắn reason_group + reason_code để phân tích Pareto theo lý do và
phân rã 6 big losses. MTBF/MTTR suy ra từ DowntimeEvent + Incident theo thiết bị.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Text, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class DowntimeEvent(Base):
    __tablename__ = "downtime_event"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    line: Mapped[str] = mapped_column(String(255), index=True)
    equipment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("equipment.equipment_id"), nullable=True, index=True)
    shift: Mapped[str] = mapped_column(String(255), default="A")
    shift_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # Cây lý do: nhóm (thiet_bi/van_hanh/chat_luong/thieu_vat_tu/chuyen_doi) → mã con
    reason_group: Mapped[str] = mapped_column(String(255), index=True)
    reason_code: Mapped[str] = mapped_column(String(64), index=True)
    reason_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Phân loại 6 big losses (availability/performance/quality loss)
    loss_category: Mapped[str] = mapped_column(String(255), default="availability")
    minutes: Mapped[float] = mapped_column(Float, default=0.0)
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
