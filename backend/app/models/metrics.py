"""Telemetry curated + OEE (tài liệu §7.7, §8.1).

- ProcessReading: chuỗi thời gian curated gắn với mẻ (nhiệt độ, °P, pH...).
  MES chỉ giữ context/curated metrics, raw history nằm ở historian (§8.1).
- OEERecord: dữ liệu ca đóng gói để tính OEE = Availability × Performance × Quality.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class ProcessReading(Base):
    __tablename__ = "process_reading"

    reading_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batch_execution.batch_id"), index=True)
    parameter: Mapped[str] = mapped_column(String(255), index=True)  # temperature | gravity | pH ...
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # source/ingest timestamp (tài liệu §8.3) — ở MVP gộp làm một mốc UTC.
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    quality: Mapped[str] = mapped_column(String(255), default="good")  # good | stale | bad


class OEERecord(Base):
    __tablename__ = "oee_record"

    oee_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    line: Mapped[str] = mapped_column(String(255), index=True)
    shift: Mapped[str] = mapped_column(String(255), default="A")
    shift_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    planned_time_min: Mapped[float] = mapped_column(Float)      # thời gian sản xuất theo kế hoạch
    downtime_min: Mapped[float] = mapped_column(Float, default=0.0)
    ideal_rate_per_min: Mapped[float] = mapped_column(Float)    # tốc độ lý tưởng (chai/phút)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    good_count: Mapped[int] = mapped_column(Integer, default=0)
    downtime_reasons: Mapped[list] = mapped_column(JSON, default=list)  # [{reason, minutes}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
