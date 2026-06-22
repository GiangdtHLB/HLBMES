"""Historian / time-series (tài liệu §8.1, §9.3).

Lưu telemetry thời gian thực theo tag (UNS namespace §9.4): value, unit, quality,
source, timestamp. SQLite phù hợp cho demo; production swap sang TimescaleDB/Influx
qua lớp services/historian.py (interface không đổi).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id, utcnow
from ..database import Base


class HistorianPoint(Base):
    __tablename__ = "historian_point"
    __table_args__ = (Index("ix_hist_tag_ts", "tag", "ts"),)

    point_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    tag: Mapped[str] = mapped_column(String, index=True)   # enterprise/site/area/device/metric
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quality: Mapped[str] = mapped_column(String, default="good")  # good | bad | stale
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # connector/gateway
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
